import asyncio
import copy
import hashlib
import inspect
import json
import time
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import quote

from config import perfecto
from config.token import PerfectoToken
from models.result import BaseResult
from tools.ai_scriptless.elements import normalize_if_statement_aliases, strip_non_api_script_fields
from tools.ai_scriptless.endpoints import ScriptEndpoints, script_endpoints
from tools.ai_scriptless.script import ScriptInput, coerce_script_dict
from tools.ai_scriptless.tree import update_flow_element_counts
from tools.utils import api_request


async def fetch_script_payload(
        token: PerfectoToken,
        test_id: str,
        endpoints: Optional[ScriptEndpoints] = None,
) -> BaseResult:
    endpoints = await script_endpoints(token, endpoints)
    script_url = endpoints.script_url + f"?itemKey={quote(test_id, safe='')}"
    return await api_request(token, "GET", endpoint=script_url)


@dataclass
class _ScriptLock:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


_script_write_locks: dict[tuple[str, str, str], _ScriptLock] = {}
_script_write_locks_guard = asyncio.Lock()


# The owner of a script every user reaches under the same item key.
SHARED_SCRIPT_OWNER = "shared"


async def script_lock_owner(token: PerfectoToken, item_key: str) -> BaseResult:
    """Who a script lock belongs to: the user for a PRIVATE test, everyone for any other.

    A PRIVATE item key names a different script for every user, so its lock is per
    user; a PUBLIC or GROUP key names one script all its users share, so they share
    its lock. The user is read from Perfecto for each write and not kept, so no token
    is held in the lock table; the username is hashed so a dump of it shows no account.
    """
    visibility = item_key.partition(":")[0]
    if visibility and visibility != "PRIVATE":
        return BaseResult(result=SHARED_SCRIPT_OWNER)
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
    so the cloud is part of the key, in lower case: it is a host name, and the header
    that brings it keeps whatever case the client sent. With several server instances
    this does not coordinate between them; a shared lock service would take its place
    behind this same call.
    """
    key = (str(cloud_name).lower(), owner, item_key)
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
# The least time one read-back gets, so the last one near the deadline can still answer.
CONFIRM_READ_MIN_SECONDS = 2.0
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


# What a save writes and the service gives back as sent (measured: info and
# options come back unchanged). The rest of the script is the service's own: uuid,
# empty and numOfFlowElements change on every save, and active, comment and status
# are added when a test is created.
AUTHORED_SECTIONS = ("parameters", "variables", "flowElements", "info", "options")


def _authored_content(script: ScriptInput) -> dict[str, Any]:
    authored = copy.deepcopy(coerce_script_dict(script))
    normalize_if_statement_aliases(authored)
    return _authored({key: authored.get(key) for key in AUTHORED_SECTIONS})


def script_fingerprint(script: ScriptInput) -> str:
    """Steps, variables, parameters and the test's settings, without what the service adds or derives.

    The settings (info, options) count too: a read that still shows a target's old
    settings must not pass for a copy that changed them.
    """
    return json.dumps(_authored_content(script), sort_keys=True, separators=(",", ":"), default=str)


def _short(value: Any, limit: int = 160) -> str:
    text = json.dumps(value, sort_keys=True, default=str)
    return text if len(text) <= limit else text[:limit - 3] + "..."


SECURED_SHOWN = "<secured>"


def _is_secured(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get("secured") is True or any(_is_secured(item) for item in value.values())
    if isinstance(value, list):
        return any(_is_secured(item) for item in value)
    return False


def _without_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: SECURED_SHOWN if key == "value" else _without_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_values(item) for item in value]
    return value


def _sent_stored(sent: Any, stored: Any) -> str:
    """The pair as the warning shows it; a value either side marks secured is shown as <secured>,
    the way the other formatters show it."""
    if _is_secured(sent) or _is_secured(stored):
        sent, stored = _without_values(sent), _without_values(stored)
    return f"sent {_short(sent)}, stored {_short(stored)}"


def _arguments_by_name(arguments: Any) -> dict[Any, Any]:
    # A multivalued parameter is stored as several arguments sharing its name, in order.
    grouped: dict[Any, list] = {}
    for argument in arguments or []:
        if isinstance(argument, dict):
            grouped.setdefault(argument.get("name"), []).append(argument)
    return {name: occurrences[0] if len(occurrences) == 1 else occurrences
            for name, occurrences in grouped.items()}


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
            lines.append(f"step {path}: {_sent_stored(one, two)}")
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
                args_sent, args_stored = _arguments_by_name(one.get(key)), _arguments_by_name(two.get(key))
                named_differences = [
                    f"step {path} argument {name}: {_sent_stored(args_sent.get(name), args_stored.get(name))}"
                    for name in sorted(set(args_sent) | set(args_stored), key=str)
                    if args_sent.get(name) != args_stored.get(name)
                ]
                # Same arguments by name, so what differs is the order they were stored in.
                lines.extend(named_differences or [
                    f"step {path} argument order: sent {_short(_argument_names(one.get(key)))}, "
                    f"stored {_short(_argument_names(two.get(key)))}"
                ])
            else:
                lines.append(f"step {path} {key}: {_sent_stored(one.get(key), two.get(key))}")


def _argument_names(arguments: Any) -> list:
    return [argument.get("name") if isinstance(argument, dict) else None for argument in arguments or []]


def _named(entries: Any) -> dict[str, Any]:
    named = {}
    for index, entry in enumerate(entries or []):
        data = entry.get("data") if isinstance(entry, dict) else None
        name = data.get("name") if isinstance(data, dict) else None
        # An entry without a name goes by its position: its content may hold a secured value.
        named[name if isinstance(name, str) and name else f"#{index}"] = entry
    return named


def describe_stored_differences(sent: ScriptInput, stored: ScriptInput) -> list[str]:
    """Where what the service stored differs from what was sent, one readable line each."""
    one, two = _authored_content(sent), _authored_content(stored)
    lines: list[str] = []
    _step_differences(one.get("flowElements") or [], two.get("flowElements") or [], "", lines)
    for section, label in (("variables", "variable"), ("parameters", "parameter")):
        sent_named, stored_named = _named(one.get(section)), _named(two.get(section))
        named_differences = [
            f"{label} {name}: {_sent_stored(sent_named.get(name), stored_named.get(name))}"
            for name in sorted(set(sent_named) | set(stored_named), key=str)
            if sent_named.get(name) != stored_named.get(name)
        ]
        if not named_differences and one.get(section) != two.get(section):
            # Same entries by name, so what differs is the order they were stored in.
            named_differences = [
                f"{section} order: sent {_short(list(sent_named))}, stored {_short(list(stored_named))}"
            ]
        lines.extend(named_differences)
    for section in ("info", "options"):
        if one.get(section) != two.get(section):
            lines.append(f"{section}: {_sent_stored(one.get(section), two.get(section))}")
    return lines


DIFFERENCES_SHOWN = 5


def _stored_differently(sent: ScriptInput, stored: ScriptInput) -> str:
    # This runs after the save answered success, so content it cannot take apart is
    # still reported as a warning, never raised.
    try:
        lines = describe_stored_differences(sent, stored)
    except Exception:
        lines = []
    if not lines:
        lines = ["the comparison could not name where (the content's order or shape differs)"]
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
        before: Optional[ScriptInput],
        endpoints: ScriptEndpoints,
) -> Optional[str]:
    """Read the script back until the save shows. Returns a warning when it does not.

    ``before`` is the version the save replaced, or None when it is not known (a new
    test, or a copy onto a key that may already hold one). The save already answered
    success, so a read that fails is retried and at worst reported, never an error.
    """
    sent_print = script_fingerprint(sent)
    before_print = script_fingerprint(before) if before is not None else None
    deadline = time.monotonic() + CONFIRM_TIMEOUT_SECONDS
    read_any, last_failure = False, None
    while True:
        stored, stored_print = None, None
        try:
            # A read that stalls must not hold the lock long past the confirmation budget.
            payload = await asyncio.wait_for(
                fetch_script_payload(token, item_key, endpoints),
                timeout=max(deadline - time.monotonic(), CONFIRM_READ_MIN_SECONDS),
            )
        except Exception as exc:
            payload, last_failure = None, f"{type(exc).__name__}: {exc or 'no answer in time'}"
        if payload is not None and payload.error:
            last_failure = str(payload.error)
        elif payload is not None:
            script = payload.result.get("script") if isinstance(payload.result, dict) else None
            try:
                stored_print = script_fingerprint(script) if isinstance(script, dict) else None
            except Exception as exc:
                last_failure = f"unreadable script: {type(exc).__name__}: {exc}"
            if stored_print is None:
                last_failure = last_failure or "the answer held no script"
            else:
                read_any, stored = True, script
                if stored_print == sent_print:
                    return None
        if time.monotonic() >= deadline:
            # Neither the version before the save nor what was sent: the service applied
            # the save and stored something else. Only the last read counts, so a version
            # caught in passing while the save was still showing is not reported.
            if stored is not None and before_print is not None and stored_print != before_print:
                return _stored_differently(sent, stored)
            if not read_any:
                return (
                    f"Saved (the service answered success), but the test could not be read back to confirm "
                    f"it ({(last_failure or 'no readable answer')[:200]}). Check with view_test_structure before "
                    f"repeating the change, so it is not applied twice."
                )
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
        endpoints: Optional[ScriptEndpoints] = None,
) -> BaseResult:
    endpoints = await script_endpoints(token, endpoints)
    working_script = copy.deepcopy(coerce_script_dict(script))
    baseline_script = copy.deepcopy(coerce_script_dict(saved_script or script))
    normalize_if_statement_aliases(working_script)
    strip_non_api_script_fields(working_script)
    strip_non_api_script_fields(baseline_script)
    update_flow_element_counts(working_script)

    draft_data = json.dumps({
        "unsavedScript": working_script,
        "savedScript": baseline_script,
    })
    draft_result = await api_request(
        token,
        "POST",
        endpoint=endpoints.draft_url,
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
        endpoint=endpoints.script_url,
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
    owner = await script_lock_owner(token, item_key)
    if owner.error:
        return owner
    async with script_write_lock(token.cloud_name, owner.result, item_key):
        # Read once: the save and the read-back go to the same service.
        endpoints = await script_endpoints(token)
        return await _save_and_confirm(token, item_key, script, saved_script, snapshot_comment, endpoints)


async def _save_and_confirm(
        token: PerfectoToken,
        item_key: str,
        script: ScriptInput,
        saved_script: Optional[ScriptInput],
        snapshot_comment: Optional[str],
        endpoints: ScriptEndpoints,
) -> BaseResult:
    """Save and read back; the caller holds the script's lock."""
    result = await _persist_script(
        token,
        item_key,
        script,
        saved_script,
        snapshot_comment,
        endpoints,
    )
    if result.error:
        return result
    unconfirmed = await _confirm_save(token, item_key, script, saved_script, endpoints)
    if unconfirmed:
        result.append_warnings([unconfirmed])
    return result


async def copy_script(
        token: PerfectoToken,
        source_key: str,
        target_key: str,
        snapshot_comment: Optional[str] = None,
) -> BaseResult:
    """Save one script under another key (UI: Save as).

    Both locks are held from the read of the source to the read-back of the copy, so
    a change to either script cannot land in between and be overwritten, and the
    settings are read once, so the copy is read from and written to the same service.
    """
    owners = {}
    for key in (source_key, target_key):
        owner = await script_lock_owner(token, key)
        if owner.error:
            return owner
        owners[key] = owner.result
    async with AsyncExitStack() as held:
        # A fixed order, so two copies running opposite ways cannot wait on each other.
        for key in sorted(owners):
            await held.enter_async_context(script_write_lock(token.cloud_name, owners[key], key))
        endpoints = await script_endpoints(token)
        payload_result = await fetch_script_payload(token, source_key, endpoints)
        if payload_result.error:
            return payload_result
        payload = payload_result.result if isinstance(payload_result.result, dict) else {}
        script = copy.deepcopy(payload.get("script", {}))
        # Onto its own key the version being replaced is known; onto another it is not.
        replaced = copy.deepcopy(script) if target_key == source_key else None
        return await _save_and_confirm(token, target_key, script, replaced, snapshot_comment, endpoints)


async def load_and_mutate(
        token: PerfectoToken,
        test_id: str,
        mutator,
        snapshot_comment: Optional[str] = None,
) -> BaseResult:
    owner = await script_lock_owner(token, test_id)
    if owner.error:
        return owner
    async with script_write_lock(token.cloud_name, owner.result, test_id):
        # Read once: the read, the save and the read-back go to the same service.
        endpoints = await script_endpoints(token)
        payload_result = await fetch_script_payload(token, test_id, endpoints)
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
            endpoints,
        )
        if result.error:
            return result
        unconfirmed = await _confirm_save(token, test_id, script, saved_script, endpoints)
        if unconfirmed:
            result.append_warnings([unconfirmed])
        return result
