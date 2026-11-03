"""Run a tool action with telemetry, session scope, and dataframe materialization."""
from typing import Any, Awaitable, Callable, Optional

from config.call_scope import resolve_mcp_session_id, user_id_for_token
from config.runtime import AppRuntime
from config.session_context import bind_call_scope
from models.result import BaseResult
from telemetry import run_tool
from tools.call_state import (
    reset_disable_dataframe_materialization,
    reset_result_format,
    set_disable_dataframe_materialization,
    set_result_format,
)
from tools.dataframe_manager import INVALID_RESULT_FORMAT_ERROR, normalize_result_format


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
) -> Any:
    """
    Bind this call's storage scope, run the tool, then store oversized results.

    Fast calls return their result directly. Methods wrapped with ``run_as_task``
    park work that exceeds a few seconds and return a task snapshot instead.
    """
    token = runtime.auth.get_token(ctx) if ctx is not None else None
    user_id = user_id_for_token(token)
    session_id = resolve_mcp_session_id(ctx)
    credential = token.token if token is not None else None
    result_format = _result_format_from_args(tool_args)

    with bind_call_scope(user_id, session_id, credential):
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
                        args=tool_args,
                        origin_manager=tool_name,
                        session_storage=runtime.storage,
                        scope_resolver=runtime.scope_resolver,
                        excluded_actions=dataframe_excluded_actions,
                    )
                finally:
                    reset_disable_dataframe_materialization(policy_token)

            return await run_tool(tool_name, action, ctx, _dispatch_and_finalize)
        finally:
            reset_result_format(format_token)
