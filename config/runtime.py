"""Process-level runtime wiring shared by all tool registrations."""
import os
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

DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8000
DEFAULT_HTTP_PATH = "/mcp"


@dataclass(frozen=True)
class HttpBindSettings:
    """Listen settings used only by the streamable-http transport."""

    host: str = DEFAULT_HTTP_HOST
    port: int = DEFAULT_HTTP_PORT
    streamable_http_path: str = DEFAULT_HTTP_PATH


def resolve_http_bind_settings() -> HttpBindSettings:
    """
    Resolve FastMCP bind settings from the environment.

    Cloud Run injects PORT; prefer FASTMCP_PORT when set, else PORT, else 8000.
    """
    host = os.getenv("FASTMCP_HOST", DEFAULT_HTTP_HOST).strip() or DEFAULT_HTTP_HOST
    port_raw = (
        os.getenv("FASTMCP_PORT")
        or os.getenv("PORT")
        or str(DEFAULT_HTTP_PORT)
    ).strip() or str(DEFAULT_HTTP_PORT)
    streamable_http_path = (
        os.getenv("FASTMCP_STREAMABLE_HTTP_PATH", DEFAULT_HTTP_PATH).strip()
        or DEFAULT_HTTP_PATH
    )
    return HttpBindSettings(
        host=host,
        port=int(port_raw),
        streamable_http_path=streamable_http_path,
    )


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
