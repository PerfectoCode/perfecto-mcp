import asyncio
import copy
import hashlib
import inspect
import json
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import quote

from config import perfecto
from config.token import PerfectoToken
from models.result import BaseResult
from tools.ai_scriptless.elements import normalize_if_statement_aliases, strip_non_api_script_fields
from tools.ai_scriptless.script import ScriptInput, coerce_script_dict
from tools.ai_scriptless.tree import update_flow_element_counts
from tools.utils import api_request


async def fetch_script_payload(token: PerfectoToken, test_id: str) -> BaseResult:
    script_url = perfecto.get_ai_scriptless_script_asset_api_url(token.cloud_name)
    script_url = script_url + f"/script-repository/script?itemKey={quote(test_id, safe='')}"
    return await api_request(token, "GET", endpoint=script_url)


@dataclass
class _ScriptLock:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


_script_write_locks: dict[tuple[str, str, str], _ScriptLock] = {}
_script_write_locks_guard = asyncio.Lock()


async def script_lock_owner(token: PerfectoToken) -> BaseResult:
    """The user a script lock belongs to, read from Perfecto for each write and not kept.

    A PRIVATE item key names a different script for every user, so the lock is per
    user. The user comes from the service rather than the token, so no token is held
    in the lock table; the username is hashed so a dump of it shows no account either.
    """
    user_url = perfecto.get_user_management_api_url(token.cloud_name) + "/current"
    result = await api_request(token, "GET", endpoint=user_url)
    if result.error:
        return result
    username = result.result.get("username") if isinstance(result.result, dict) else None
    if not username:
        return BaseResult(error="Could not read the current Perfecto user, so the test was not changed.")
    return BaseResult(result=hashlib.sha256(username.encode("utf-8")).hexdigest())


@asynccontextmanager
async def script_write_lock(cloud_name: str, owner: str, item_key: str):
    """Serialize writes to one user's script in this process; the entry lives only while in use.

    ``owner`` comes from script_lock_owner. One item key can exist on several clouds,
    so the cloud is part of the key. With several server instances this does not
    coordinate between them; a shared lock service would take its place behind this
    same call.
    """
    key = (str(cloud_name), owner, item_key)
    async with _script_write_locks_guard:
        held = _script_write_locks.setdefault(key, _ScriptLock())
        held.users += 1
    try:
        async with held.lock:
            yield
    finally:
        async with _script_write_locks_guard:
            held.users -= 1
            if held.users == 0 and _script_write_locks.get(key) is held:
                del _script_write_locks[key]


# A read made right after a save can return the version from before it, and
# writing the whole script back on top of that read erases the save. Reading the
# script back until the save shows, while still holding its lock, keeps the next
# change from starting on such a read. Nothing is kept between requests.
CONFIRM_TIMEOUT_SECONDS = 6.0
CONFIRM_EVERY_SECONDS = 1.0
_SERVICE_KEYS = frozenset({"uuid", "empty", "numOfFlowElements"})


def _authored(value: Any) -> Any:
    if isinstance(value, dict):
        kept = {}
        for key, item in value.items():
            if key in _SERVICE_KEYS:
                continue
            item = _authored(item)
            if item not in (None, [], {}):
                kept[key] = item
        return kept
    if isinstance(value, list):
        return [_authored(item) for item in value]
    return value


def _authored_content(script: ScriptInput) -> dict[str, Any]:
    authored = copy.deepcopy(coerce_script_dict(script))
    normalize_if_statement_aliases(authored)
    return _authored({key: authored.get(key) for key in ("parameters", "variables", "flowElements")})


def script_fingerprint(script: ScriptInput) -> str:
    """Steps, variables and parameters, without the fields the service adds or derives."""
    return json.dumps(_authored_content(script), sort_keys=True, separators=(",", ":"), default=str)


def _short(value: Any, limit: int = 160) -> str:
    text = json.dumps(value, sort_keys=True, default=str)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _step_label(element: Any) -> str:
    if not isinstance(element, dict):
        return _short(element)
    label = str(element.get("@type", "?"))
    if element.get("command"):
        label += f" {element.get('command')}/{element.get('subcommand')}"
    if element.get("name"):
        label += f' "{element["name"]}"'
    return label


def _step_differences(sent: list, stored: list, prefix: str, lines: list[str]) -> None:
    for index in range(max(len(sent), len(stored))):
        path = f"{prefix}{index}"
        if index >= len(stored):
            lines.append(f"step {path} ({_step_label(sent[index])}): sent, not stored")
            continue
        if index >= len(sent):
            lines.append(f"step {path} ({_step_label(stored[index])}): stored, not sent")
            continue
        one, two = sent[index], stored[index]
        if one == two:
            continue
        if not isinstance(one, dict) or not isinstance(two, dict):
            lines.append(f"step {path}: sent {_short(one)}, stored {_short(two)}")
            continue
        for key in sorted(set(one) | set(two)):
            if one.get(key) == two.get(key):
                continue
            if key == "flowElements":
                _step_differences(one.get(key) or [], two.get(key) or [], f"{path}.", lines)
            elif key == "branches":
                branches_sent, branches_stored = one.get(key) or [], two.get(key) or []
                for branch in range(max(len(branches_sent), len(branches_stored))):
                    _step_differences(
                        (branches_sent[branch] if branch < len(branches_sent) else {}).get("flowElements") or [],
                        (branches_stored[branch] if branch < len(branches_stored) else {}).get("flowElements") or [],
                        f"{path}.b{branch}.",
                        lines,
                    )
            elif key == "arguments":
                args_sent = {arg.get("name"): arg for arg in one.get(key) or [] if isinstance(arg, dict)}
                args_stored = {arg.get("name"): arg for arg in two.get(key) or [] if isinstance(arg, dict)}
                for name in sorted(set(args_sent) | set(args_stored), key=str):
                    if args_sent.get(name) != args_stored.get(name):
                        lines.append(
                            f"step {path} argument {name}: sent {_short(args_sent.get(name))}, "
                            f"stored {_short(args_stored.get(name))}"
                        )
            else:
                lines.append(f"step {path} {key}: sent {_short(one.get(key))}, stored {_short(two.get(key))}")


def _named(entries: Any) -> dict[str, Any]:
    named = {}
    for entry in entries or []:
        name = (entry.get("data") or {}).get("name") if isinstance(entry, dict) else None
        named[name or _short(entry)] = entry
    return named


def describe_stored_differences(sent: ScriptInput, stored: ScriptInput) -> list[str]:
    """Where what the service stored differs from what was sent, one readable line each."""
    one, two = _authored_content(sent), _authored_content(stored)
    lines: list[str] = []
    _step_differences(one.get("flowElements") or [], two.get("flowElements") or [], "", lines)
    for section, label in (("variables", "variable"), ("parameters", "parameter")):
        sent_named, stored_named = _named(one.get(section)), _named(two.get(section))
        for name in sorted(set(sent_named) | set(stored_named), key=str):
            if sent_named.get(name) != stored_named.get(name):
                lines.append(
                    f"{label} {name}: sent {_short(sent_named.get(name))}, stored {_short(stored_named.get(name))}"
                )
    return lines


DIFFERENCES_SHOWN = 5


def _stored_differently(sent: ScriptInput, stored: ScriptInput) -> str:
    lines = describe_stored_differences(sent, stored)
    shown = "; ".join(lines[:DIFFERENCES_SHOWN])
    if len(lines) > DIFFERENCES_SHOWN:
        shown += f"; and {len(lines) - DIFFERENCES_SHOWN} more"
    return (
        f"Saved, but the service stored something different from what was sent: {shown}. "
        f"The service accepts some content only in another form, dropping or converting the rest, "
        f"so part of this change may not be in a form it takes as given; another edit to this test saved "
        f"at the same time would also show here. Check with view_test_structure; sending the same change "
        f"again is likely to give the same result."
    )


async def _confirm_save(
        token: PerfectoToken,
        item_key: str,
        sent: ScriptInput,
        before: ScriptInput,
) -> Optional[str]:
    """Read the script back until the save shows. Returns a warning when it does not."""
    sent_print, before_print = script_fingerprint(sent), script_fingerprint(before)
    deadline = time.monotonic() + CONFIRM_TIMEOUT_SECONDS
    while True:
        payload = await fetch_script_payload(token, item_key)
        stored = None
        if not payload.error and isinstance(payload.result, dict):
            stored = payload.result.get("script", {})
            if script_fingerprint(stored) == sent_print:
                return None
        if time.monotonic() >= deadline:
            # Neither the version before the save nor what was sent: the service applied
            # the save and stored something else. Only the last read counts, so a version
            # caught in passing while the save was still showing is not reported.
            if stored is not None and script_fingerprint(stored) != before_print:
                return _stored_differently(sent, stored)
            return (
                f"Saved (the service answered success), but reading the test back for "
                f"{CONFIRM_TIMEOUT_SECONDS:g}s did not show the change. The service may still be applying "
                f"it or may not have kept it. Check with view_test_structure before repeating the change, "
                f"so it is not applied twice."
            )
        await asyncio.sleep(CONFIRM_EVERY_SECONDS)


async def _persist_script(
        token: PerfectoToken,
        item_key: str,
        script: ScriptInput,
        saved_script: Optional[ScriptInput] = None,
        snapshot_comment: Optional[str] = None,
) -> BaseResult:
    working_script = copy.deepcopy(coerce_script_dict(script))
    baseline_script = copy.deepcopy(coerce_script_dict(saved_script or script))
    normalize_if_statement_aliases(working_script)
    strip_non_api_script_fields(working_script)
    strip_non_api_script_fields(baseline_script)
    update_flow_element_counts(working_script)

    draft_url = perfecto.get_ai_scriptless_script_asset_api_url(token.cloud_name)
    draft_url = draft_url + "/script-draft-repository/draft"
    draft_data = json.dumps({
        "unsavedScript": working_script,
        "savedScript": baseline_script,
    })
    draft_result = await api_request(
        token,
        "POST",
        endpoint=draft_url,
        json={
            "path": item_key,
            "type": "MOBILE_IDE_SCRIPT",
            "data": draft_data,
        },
    )
    if draft_result.error:
        return draft_result
    draft_key = draft_result.result.get("key")
    if not draft_key:
        return BaseResult(error="Draft creation failed: missing draft key in response")

    script_url = perfecto.get_ai_scriptless_script_asset_api_url(token.cloud_name) \
        + "/script-repository/script"
    save_body: dict[str, Any] = {
        "script": working_script,
        "itemKey": item_key,
        "draftKey": draft_key,
    }
    if snapshot_comment:
        save_body["snapshotComment"] = snapshot_comment
    save_result = await api_request(
        token,
        "POST",
        endpoint=script_url,
        json=save_body,
    )
    if save_result.error:
        return save_result

    result: dict[str, Any] = {
        "item_key": item_key,
        "draft_key": draft_key,
        "status": save_result.result.get("status", "success") if isinstance(save_result.result, dict) else "success",
        "flow_element_count": len(working_script.get("flowElements", [])),
    }
    if snapshot_comment:
        result["snapshot_comment"] = snapshot_comment
    result["notes"] = [
        "Perfecto adds a new snapshot history entry on every script save.",
        "Use list_snapshots with test_id to see version history after saving.",
    ]
    if snapshot_comment:
        result["notes"].append(
            "The comment labels the version this save created (UI: Save with comment). It shows on "
            "'<current>' only until the next save, after which it stays with its own history entry."
        )
    else:
        result["notes"].append(
            "Saving without comment still creates a history entry; pass comment to label the current version."
        )
    return BaseResult(result=result)


async def persist_script(
        token: PerfectoToken,
        item_key: str,
        script: ScriptInput,
        saved_script: Optional[ScriptInput] = None,
        snapshot_comment: Optional[str] = None,
) -> BaseResult:
    owner = await script_lock_owner(token)
    if owner.error:
        return owner
    async with script_write_lock(token.cloud_name, owner.result, item_key):
        return await _persist_script(
            token,
            item_key,
            script,
            saved_script,
            snapshot_comment,
        )


async def load_and_mutate(
        token: PerfectoToken,
        test_id: str,
        mutator,
        snapshot_comment: Optional[str] = None,
) -> BaseResult:
    owner = await script_lock_owner(token)
    if owner.error:
        return owner
    async with script_write_lock(token.cloud_name, owner.result, test_id):
        payload_result = await fetch_script_payload(token, test_id)
        if payload_result.error:
            return payload_result
        payload = payload_result.result
        script = copy.deepcopy(payload.get("script", {}))
        saved_script = copy.deepcopy(payload.get("script", {}))
        normalize_if_statement_aliases(script)
        try:
            outcome = mutator(script)
            # Mutators may be async when they need the API (e.g. command definitions).
            if inspect.isawaitable(outcome):
                await outcome
        except ValueError as exc:
            return BaseResult(error=str(exc))
        result = await _persist_script(
            token,
            test_id,
            script,
            saved_script,
            snapshot_comment,
        )
        if result.error:
            return result
        unconfirmed = await _confirm_save(token, test_id, script, saved_script)
        if unconfirmed:
            result.append_warnings([unconfirmed])
        return result
