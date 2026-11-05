"""Require a chat session on every Perfecto tool except the session tool itself."""
from __future__ import annotations

import logging
from typing import Any, Optional, Union

from config.perfecto import (
    PERFECTO_CLOUD_NAME_NOT_SET_MESSAGE,
    SECURITY_TOKEN_NOT_SET_MESSAGE,
)
from config.runtime import AppRuntime
from config.session import (
    SESSION_TOOL_NAME,
    ChatSession,
    SessionError,
    SessionErrorCode,
    is_valid_session_id,
)
from config.session_context import (
    Identity,
    current_credential,
    current_identity,
    current_session,
)
from config.call_scope import user_id_for_token
from config.token import PerfectoToken
from models.result import BaseResult

logger = logging.getLogger(__name__)

SESSION_ID_ARG = "session_id"
SESSION_HINT = (
    f"- **CRITICAL (session)**: Every call requires `{SESSION_ID_ARG}` next to `action` "
    f"(or inside args). Get it once per conversation with `{SESSION_TOOL_NAME}` action 'get' "
    "and reuse it in every call; never reuse a session_id from another conversation. If a call "
    "returns error_code SESSION_REQUIRED, SESSION_INVALID or SESSION_EXPIRED, get a new "
    "session_id, use it from then on, and re-run the calls whose tasks or dataframes you still need."
)


def session_error(code: SessionErrorCode) -> BaseResult:
    error = SessionError(code)
    return BaseResult(error=error.message, error_code=error.code.value)


def credential_for_token(token: Optional[PerfectoToken]) -> Optional[str]:
    """Opaque security token the session is bound to. The cloud is part of the owner id."""
    if token is None or not token.token:
        return None
    return token.token


def identity_for_token(token: Optional[PerfectoToken]) -> Union[Identity, BaseResult]:
    """
    Owner of sessions and partitions for this call.

    Perfecto already authenticated the security token at the transport. The owner
    id is a hash of that token plus the cloud, so two credentials never share a
    session. There is no separate identity API.
    """
    if token is None or not getattr(token, "token", None):
        return BaseResult(error=SECURITY_TOKEN_NOT_SET_MESSAGE)
    if not getattr(token, "cloud_name", None):
        return BaseResult(error=PERFECTO_CLOUD_NAME_NOT_SET_MESSAGE)
    return Identity(user_id=user_id_for_token(token))


async def validate_session(
        runtime: AppRuntime,
        requested: Any,
        identity: Identity,
        credential: Optional[str],
) -> Union[BaseResult, ChatSession]:
    if requested is None or (isinstance(requested, str) and not requested.strip()):
        return session_error(SessionErrorCode.REQUIRED)
    if not is_valid_session_id(requested) or not credential:
        return session_error(SessionErrorCode.INVALID)
    try:
        return await runtime.sessions.touch(requested, identity.user_id, credential)
    except SessionError as exc:
        return session_error(exc.code)
    except Exception:
        logger.exception("Session validation failed")
        return session_error(SessionErrorCode.UNAVAILABLE)


def annotate_session_requirements(mcp: Any) -> None:
    """Tell agents, from the tool description, that session_id is required."""
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        return
    if not isinstance(mcp, FastMCP):
        return
    for tool in mcp._tool_manager.list_tools():
        if tool.name == SESSION_TOOL_NAME:
            continue
        description = tool.description or ""
        if SESSION_HINT not in description:
            tool.description = f"{description.rstrip()}\n{SESSION_HINT}\n"
        parameters = tool.parameters if isinstance(tool.parameters, dict) else None
        if parameters is None:
            continue
        arguments = parameters.setdefault("properties", {}).get("arguments")
        if isinstance(arguments, dict):
            note = f" Include `{SESSION_ID_ARG}` from `{SESSION_TOOL_NAME}` action 'get'."
            current = arguments.get("description") or "Dictionary with arguments."
            if SESSION_ID_ARG not in current:
                arguments["description"] = f"{current.rstrip()}.{note}" if not current.endswith(".") else f"{current}{note}"
