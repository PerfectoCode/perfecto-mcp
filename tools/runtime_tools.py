"""Run a tool action with telemetry, a chat session, and dataframe materialization."""
from typing import Any, Awaitable, Callable, Optional

from config.runtime import AppRuntime
from config.session_context import bind_session_context, current_identity, current_session
from models.result import BaseResult
from telemetry import run_tool
from tools.call_state import (
    reset_disable_dataframe_materialization,
    reset_result_format,
    set_disable_dataframe_materialization,
    set_result_format,
)
from tools.dataframe_manager import INVALID_RESULT_FORMAT_ERROR, normalize_result_format
from tools.session_gate import (
    SESSION_ID_ARG,
    credential_for_token,
    identity_for_token,
    validate_session,
)


def _result_format_from_args(tool_args: Any) -> str:
    if not isinstance(tool_args, dict):
        return "auto"
    return normalize_result_format(tool_args.get("result_format", "auto"))


async def run_tool_with_runtime(
        runtime: AppRuntime,
        tool_name: str,
        action: str,
        ctx: Any,
        dispatch: Callable[[], Awaitable[Any]],
        *,
        tool_args: Any = None,
        dataframe_excluded_actions: Optional[set[str]] = None,
        disable_dataframe_materialization: bool = False,
        requires_session: bool = True,
) -> Any:
    """
    Validate the caller and chat session, run the tool, then store oversized results.

    ``perfecto_session`` passes ``requires_session=False``. Every other tool
    needs the ``session_id`` from that tool. Nested calls inherit the session
    already bound for this call. Fast calls return their result directly.
    Methods wrapped with ``run_as_task`` park work that exceeds a few seconds.
    """
    call_args = dict(tool_args) if isinstance(tool_args, dict) else {}
    requested = call_args.pop(SESSION_ID_ARG, None)
    if isinstance(requested, str):
        requested = requested.strip() or None
    result_format = _result_format_from_args(call_args)

    inherited = current_identity()
    if inherited is not None:
        inherited_session = current_session()
        if requires_session:
            if inherited_session is None:
                from tools.session_gate import session_error
                from config.session import SessionErrorCode
                return session_error(SessionErrorCode.REQUIRED)
            if requested is not None and requested != inherited_session.session_id:
                from tools.session_gate import session_error
                from config.session import SessionErrorCode
                return session_error(SessionErrorCode.INVALID)
        return await _execute(
            runtime, tool_name, action, ctx, dispatch, call_args, result_format,
            dataframe_excluded_actions, disable_dataframe_materialization,
            inherited_session.session_id if inherited_session is not None else None,
        )

    token = runtime.auth.get_token(ctx) if ctx is not None else None
    identity = identity_for_token(token)
    if isinstance(identity, BaseResult):
        return identity
    credential = credential_for_token(token)

    session = None
    if requires_session:
        validated = await validate_session(runtime, requested, identity, credential)
        if isinstance(validated, BaseResult):
            return validated
        session = validated

    with bind_session_context(identity, session, credential):
        return await _execute(
            runtime, tool_name, action, ctx, dispatch, call_args, result_format,
            dataframe_excluded_actions, disable_dataframe_materialization,
            session.session_id if session is not None else None,
        )


async def _execute(
        runtime: AppRuntime,
        tool_name: str,
        action: str,
        ctx: Any,
        dispatch: Callable[[], Awaitable[Any]],
        call_args: dict,
        result_format: str,
        dataframe_excluded_actions: Optional[set[str]],
        disable_dataframe_materialization: bool,
        session_id: Optional[str],
) -> Any:
    format_token = set_result_format("auto" if result_format == "invalid" else result_format)
    try:
        if result_format == "invalid":
            return BaseResult(error=INVALID_RESULT_FORMAT_ERROR)

        async def _dispatch_and_finalize() -> Any:
            policy_token = set_disable_dataframe_materialization(disable_dataframe_materialization)
            try:
                result = await dispatch()
                if disable_dataframe_materialization or result is None:
                    return result
                from tools.dataframe_manager import finalize_tool_result

                return await finalize_tool_result(
                    result,
                    action=action,
                    args=call_args,
                    origin_manager=tool_name,
                    session_storage=runtime.storage,
                    scope_resolver=runtime.scope_resolver,
                    excluded_actions=dataframe_excluded_actions,
                )
            finally:
                reset_disable_dataframe_materialization(policy_token)

        result = await run_tool(tool_name, action, ctx, _dispatch_and_finalize)
    finally:
        reset_result_format(format_token)

    if isinstance(result, BaseResult) and not result.error and session_id and not result.session_id:
        result.session_id = session_id
    return result
