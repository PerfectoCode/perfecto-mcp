import asyncio
import copy
import inspect
import json
from contextlib import asynccontextmanager
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
    script_url = perfecto.get_ai_scriptless_api_url(token.cloud_name)
    script_url = script_url + f"/script?itemKey={quote(test_id, safe='')}"
    return await api_request(token, "GET", endpoint=script_url)


_script_write_locks: dict[str, asyncio.Lock] = {}
_script_write_locks_guard = asyncio.Lock()


async def _get_script_write_lock(item_key: str) -> asyncio.Lock:
    async with _script_write_locks_guard:
        lock = _script_write_locks.get(item_key)
        if lock is None:
            lock = asyncio.Lock()
            _script_write_locks[item_key] = lock
        return lock


@asynccontextmanager
async def script_write_lock(item_key: str):
    lock = await _get_script_write_lock(item_key)
    async with lock:
        yield


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

    draft_url = perfecto.get_ai_scriptless_draft_api_url(token.cloud_name)
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

    script_url = perfecto.get_ai_scriptless_api_url(token.cloud_name) + "/script"
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
            "The comment labels the '<current>' entry in list_snapshots (UI: Save with comment)."
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
    async with script_write_lock(item_key):
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
    async with script_write_lock(test_id):
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
        return await _persist_script(
            token,
            test_id,
            script,
            saved_script,
            snapshot_comment,
        )
