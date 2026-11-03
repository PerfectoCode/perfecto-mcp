"""Derive a storage partition from the Perfecto credential and MCP session."""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from config.token import PerfectoToken


def user_id_for_token(token: Optional[PerfectoToken]) -> str:
    """
    Stable partition owner for a security token and cloud.

    The raw token is never used as a storage key. Anonymous calls share one
    owner so local tests without a token still have a scope.
    """
    raw = getattr(token, "token", None) if token is not None else None
    if not raw:
        return "anonymous"
    cloud = getattr(token, "cloud_name", None) or ""
    digest = hashlib.sha256(f"{cloud}\n{raw}".encode("utf-8")).hexdigest()
    return digest[:32]


def resolve_mcp_session_id(ctx: Any) -> str:
    """
    MCP session that owns dataframes and tasks for this call.

    Streamable HTTP clients send ``mcp-session-id``. FastMCP also exposes it as
    ``ctx.session_id``. Stdio and calls without a session share ``local``, which
    is one partition per process for that credential.
    """
    if ctx is None:
        return "local"

    request = None
    try:
        request = ctx.request_context.request
    except Exception:
        request = None
    headers = getattr(request, "headers", None)
    if headers is not None:
        raw = headers.get("mcp-session-id")
        if raw and str(raw).strip():
            return str(raw).strip()

    try:
        session_id = ctx.session_id
        if session_id:
            return str(session_id)
    except Exception:
        pass
    return "local"
