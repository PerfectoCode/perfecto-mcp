"""Helpers to read the per-session user config carried by the MCP context."""
from typing import Any

from config.auth import PERFECTO_TOKEN_STATE_ATTR, PERFECTO_USER_CONFIG_STATE_ATTR


def get_request_context(ctx: Any) -> Any:
    return getattr(ctx, "request_context", None)


def get_request_state(ctx: Any) -> Any:
    request_context = get_request_context(ctx)
    request = getattr(request_context, "request", None)
    return getattr(request, "state", None)


def resolve_ctx_user_config(ctx: Any) -> dict[str, Any]:
    request_context = get_request_context(ctx)
    request_state = get_request_state(ctx)

    request_context_config = getattr(request_context, PERFECTO_USER_CONFIG_STATE_ATTR, None)
    if isinstance(request_context_config, dict):
        return request_context_config

    request_state_config = getattr(request_state, PERFECTO_USER_CONFIG_STATE_ATTR, None)
    if isinstance(request_state_config, dict):
        return request_state_config

    return {}


def resolve_ctx_token(ctx: Any) -> Any:
    user_config = resolve_ctx_user_config(ctx)
    request_state = get_request_state(ctx)
    request_state_token = getattr(request_state, PERFECTO_TOKEN_STATE_ATTR, None)
    return user_config.get("token") or request_state_token
