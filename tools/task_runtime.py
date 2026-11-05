"""Schedule manager methods as session tasks when they run longer than a few seconds."""
from __future__ import annotations

import asyncio
import functools
import inspect
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from models.result import BaseResult
from tools.call_state import (
    _disable_dataframe_materialization,
    _result_format_context,
    _task_management_enabled,
)

_result_debug_enabled = False

def _attach_task_debug(result: BaseResult, task_record: Any):
    if not _result_debug_enabled:
        return
    if not isinstance(result, BaseResult) or task_record is None:
        return
    if not hasattr(result, "debug"):
        return
    debug = result.debug if isinstance(result.debug, dict) else {}
    task_debug: Dict[str, int] = {}
    if task_record.started_running_at is not None:
        task_debug["queue_wait_ms"] = int((task_record.started_running_at - task_record.created_at) * 1000)
        end_ts = task_record.finished_at if task_record.finished_at is not None else task_record.last_updated_at
        task_debug["run_ms"] = int((end_ts - task_record.started_running_at) * 1000)
    task_debug["lifecycle_ms"] = int((task_record.last_updated_at - task_record.created_at) * 1000)
    debug["task"] = task_debug
    result.debug = debug


def _serialize_action_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _serialize_action_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize_action_value(v) for v in value]
    return repr(value)


async def execute_with_task_management(
        action_payload: Dict[str, Any],
        coro_factory: Callable[[], Awaitable[Any]],
        time_to_live_ms: Optional[int] = None,
        fast_response_threshold_seconds: float = 5.0,
        scope: Optional[Any] = None,
) -> BaseResult:
    # Deferred import avoids circular dependency: utils → async_task_manager → dataframe_manager → utils.
    from config.storage import SessionScope
    from tools.async_task_manager import (
        submit_task,
        get_task_record,
        remove_task,
        task_snapshot,
    )

    if not isinstance(scope, SessionScope):
        # Fail closed: a task without its chat session would land in a shared partition.
        return BaseResult(error="Task could not be scheduled: no session scope for this call.")
    resolved_scope = scope
    wait_started = time.monotonic()
    try:
        task_id = await submit_task(
            action_payload,
            coro_factory,
            time_to_live_ms=time_to_live_ms,
            scope=resolved_scope,
        )
    except RuntimeError as exc:
        return BaseResult(error=str(exc))
    task_record = await get_task_record(task_id, scope=resolved_scope)
    if not task_record or not task_record.asyncio_task:
        return BaseResult(error="Task could not be scheduled.")

    try:
        await asyncio.wait_for(
            asyncio.shield(task_record.asyncio_task),
            timeout=fast_response_threshold_seconds,
        )
        latest_record = await get_task_record(task_id, scope=resolved_scope)
        if not latest_record or latest_record.result is None:
            await remove_task(task_id, scope=resolved_scope)
            return BaseResult(error="Task finished without result.")
        final_result = latest_record.result
        failure = getattr(latest_record, "failure", None)
        _attach_task_debug(final_result, latest_record)
        debug = getattr(final_result, "debug", None)
        if isinstance(debug, dict):
            debug.setdefault("task", {})
            debug["task"]["sync_wait_ms"] = int((time.monotonic() - wait_started) * 1000)
        await remove_task(task_id, scope=resolved_scope)
        if failure is not None:
            raise failure
        return final_result
    except asyncio.TimeoutError:
        latest_record = await get_task_record(task_id, scope=resolved_scope)
        if not latest_record:
            return BaseResult(error="Task was not found after scheduling.")
        snapshot = task_snapshot(latest_record, include_result=False)
        timeout_result = BaseResult(
            result=[snapshot],
            info=[
                "Long-running operation accepted. Use perfecto_tools with action 'tasks_status' to monitor status."
            ],
        )
        _attach_task_debug(timeout_result, latest_record)
        debug = getattr(timeout_result, "debug", None)
        if isinstance(debug, dict):
            debug.setdefault("task", {})
            debug["task"]["sync_wait_ms"] = int((time.monotonic() - wait_started) * 1000)
        timeout_result.mark_pending_task(task_id, resolved_scope)
        return timeout_result


def run_as_task(
        time_to_live_ms: Optional[int] = None,
        fast_response_threshold_seconds: float = 5.0,
):
    def decorator(func: Callable[..., Awaitable[Any]]):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            if _task_management_enabled.get():
                return await func(self, *args, **kwargs)

            try:
                signature = inspect.signature(func)
                bound = signature.bind(self, *args, **kwargs)
                bound.apply_defaults()
                named_params = {
                    key: _serialize_action_value(value)
                    for key, value in bound.arguments.items()
                    if key != "self"
                }
            except Exception:
                named_params = {}

            action_payload = {
                "manager": self.__class__.__name__,
                "method": func.__name__,
                "args": _serialize_action_value(args),
                "kwargs": _serialize_action_value(kwargs),
                "params": named_params,
                "result_format": _result_format_context.get(),
                "disable_dataframe_materialization": bool(
                    _disable_dataframe_materialization.get()
                ),
            }

            from config.session_context import SessionContextMissing
            from tools.async_task_manager import session_scope_from_manager

            try:
                scope = session_scope_from_manager(self)
            except SessionContextMissing:
                # Only public tools (help/skills) run without a session: no task and
                # no partition, just run inline. Gated tools always have a session.
                return await func(self, *args, **kwargs)
            token = _task_management_enabled.set(True)
            try:
                coro_factory = lambda: func(self, *args, **kwargs)
                return await execute_with_task_management(
                    action_payload=action_payload,
                    coro_factory=coro_factory,
                    time_to_live_ms=time_to_live_ms,
                    fast_response_threshold_seconds=fast_response_threshold_seconds,
                    scope=scope,
                )
            finally:
                _task_management_enabled.reset(token)

        return wrapper

    return decorator


