"""Process-level runtime wiring shared by all tool registrations."""
from dataclasses import dataclass
from typing import Any, Literal, Optional

from config.auth import (
    AuthPort,
    PERFECTO_USER_CONFIG_STATE_ATTR,
    HttpAuthProvider,
    StdioAuthProvider,
)
from config.token import PerfectoToken

Transport = Literal["stdio", "streamable-http"]


@dataclass(frozen=True)
class AppRuntime:
    """Process-level collaborators shared by tool registrations."""

    transport: Transport
    auth: AuthPort
    user_config: dict[str, Any]

    def resolve_user_config(self, ctx: Any) -> dict[str, Any]:
        user_config = dict(self.user_config)
        user_config.update(_read_ctx_user_config(ctx))
        token = self.auth.get_token(ctx)
        if token is not None:
            user_config["token"] = token
        return user_config

    def configure_context(self, ctx: Any) -> dict[str, Any]:
        user_config = self.resolve_user_config(ctx)
        _hydrate_ctx_user_config(ctx, user_config)
        return user_config


def _read_ctx_user_config(ctx: Any) -> dict[str, Any]:
    if ctx is None:
        return {}

    user_config: dict[str, Any] = {}
    request_context = getattr(ctx, "request_context", None)
    request = getattr(request_context, "request", None)
    request_state = getattr(request, "state", None)

    for target, attr_name in (
        (ctx, "user_config"),
        (request_context, PERFECTO_USER_CONFIG_STATE_ATTR),
        (request_state, PERFECTO_USER_CONFIG_STATE_ATTR),
    ):
        request_config = getattr(target, attr_name, None)
        if isinstance(request_config, dict):
            user_config.update(request_config)

    return user_config


def _hydrate_ctx_user_config(ctx: Any, user_config: dict[str, Any]) -> None:
    if ctx is None:
        return

    config_copy = dict(user_config)
    request_context = getattr(ctx, "request_context", None)
    request = getattr(request_context, "request", None)
    request_state = getattr(request, "state", None)

    for target in (request_context, request_state):
        if target is not None:
            setattr(target, PERFECTO_USER_CONFIG_STATE_ATTR, dict(config_copy))


def build_runtime(
        transport: Transport,
        startup_token: Optional[PerfectoToken] = None,
) -> AppRuntime:
    """
    Compose auth for the selected transport.

    - stdio: process-lifetime ``startup_token``.
    - streamable-http: request-scoped Bearer auth.
    """
    if transport == "stdio":
        stdio_user_config = {
            "startup_token": startup_token,
            "token": startup_token,
            "cloud_name": startup_token.cloud_name if startup_token else None,
        }
        return AppRuntime(
            transport=transport,
            auth=StdioAuthProvider(startup_token),
            user_config=stdio_user_config,
        )

    if transport == "streamable-http":
        return AppRuntime(
            transport=transport,
            auth=HttpAuthProvider(),
            user_config={},
        )

    raise ValueError(f"Unknown transport: {transport}")
