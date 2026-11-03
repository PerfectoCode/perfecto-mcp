"""Request-scoped identity and session used to partition dataframes and tasks.

Perfecto does not ask the model for a separate chat session id. The tool
entrypoint binds a scope derived from the security token and the MCP session
before any manager code runs. Storage then reads that scope from these
context vars, the same way the BlazeMeter MCP reads a validated chat session.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class Identity:
    user_id: str


@dataclass(frozen=True)
class ChatSession:
    session_id: str


_current_identity: contextvars.ContextVar[Optional[Identity]] = contextvars.ContextVar(
    "perfecto_current_identity", default=None
)
_current_session: contextvars.ContextVar[Optional[ChatSession]] = contextvars.ContextVar(
    "perfecto_current_session", default=None
)
_current_credential: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "perfecto_current_credential", default=None
)


class SessionContextMissing(RuntimeError):
    """Session-scoped state was used outside a tool call that bound a scope."""


def current_identity() -> Optional[Identity]:
    return _current_identity.get()


def current_session() -> Optional[ChatSession]:
    return _current_session.get()


def current_credential() -> Optional[str]:
    return _current_credential.get()


@contextmanager
def bind_session_context(
        identity: Identity,
        session: Optional[ChatSession] = None,
        credential: Optional[str] = None,
) -> Iterator[None]:
    """Bind identity, session and credential for the duration of one tool call."""
    identity_token = _current_identity.set(identity)
    session_token = _current_session.set(session)
    credential_token = _current_credential.set(credential)
    try:
        yield
    finally:
        _current_credential.reset(credential_token)
        _current_session.reset(session_token)
        _current_identity.reset(identity_token)


@contextmanager
def bind_call_scope(user_id: str, session_id: str, credential: Optional[str] = None) -> Iterator[None]:
    """Bind the partition key for one Perfecto tool call."""
    with bind_session_context(Identity(user_id), ChatSession(session_id), credential):
        yield
