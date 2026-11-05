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
from config.cache import CachePort, build_cache_from_env
from config.service_auth import service_caller_token
from config.session import HttpSessionProvider, InMemorySessionProvider, SessionPort
from config.storage import (
    DefaultSessionScopeResolver,
    HttpSessionStorageProvider,
    InMemorySessionStorageProvider,
    SessionScopeResolverPort,
    SessionStoragePort,
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
    storage: SessionStoragePort
    scope_resolver: SessionScopeResolverPort
    cache: CachePort
    sessions: SessionPort

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
    try:
        setattr(ctx, "user_config", dict(config_copy))
    except Exception:
        pass
    request_context = getattr(ctx, "request_context", None)
    request = getattr(request_context, "request", None)
    request_state = getattr(request, "state", None)

    for target in (request_context, request_state):
        if target is not None:
            setattr(target, PERFECTO_USER_CONFIG_STATE_ATTR, dict(config_copy))


def _storage_base_url() -> str:
    return os.getenv("PERFECTO_STORAGE_API_BASE_URL", "").strip()


def _sessions_for(
        transport: Transport,
        storage: SessionStoragePort,
        storage_base_url: str,
        caller_token: str,
) -> SessionPort:
    """
    Stdio, and HTTP without a storage URL, keep the session registry in this
    process and drop a purged session's partition. HTTP with a storage URL
    uses the storage service ``/sessions`` registry.
    """
    if transport == "streamable-http" and storage_base_url:
        return HttpSessionProvider(base_url=storage_base_url, caller_token=caller_token)
    on_purge = getattr(storage, "discard_session", None)
    return InMemorySessionProvider(on_purge=on_purge)


def _build_storage_and_cache(transport: Transport) -> tuple[SessionStoragePort, CachePort, str, str]:
    """
    Stdio, and HTTP without a storage URL, keep partitions and the method cache
    in this process. HTTP with ``PERFECTO_STORAGE_API_BASE_URL`` uses the shared
    storage service so dataframes, tasks and cache entries survive across workers.
    """
    storage_base_url = _storage_base_url()
    if transport == "streamable-http" and storage_base_url:
        caller_token = service_caller_token()
        if not caller_token:
            raise ValueError(
                "PERFECTO_MCP_STORAGE_CALLER_TOKEN is required when "
                "PERFECTO_STORAGE_API_BASE_URL is set."
            )
        storage: SessionStoragePort = HttpSessionStorageProvider(
            base_url=storage_base_url,
            caller_token=caller_token,
        )
        storage.ensure_available()
        return storage, build_cache_from_env(
            "streamable-http",
            storage_base_url=storage_base_url,
            caller_token=caller_token,
        ), storage_base_url, caller_token

    # In-memory cache factory is the stdio path of build_cache_from_env.
    return InMemorySessionStorageProvider(), build_cache_from_env("stdio"), "", ""


def build_runtime(
        transport: Transport,
        startup_token: Optional[PerfectoToken] = None,
) -> AppRuntime:
    """
    Compose auth, chat sessions, session storage and the method cache.

    - stdio: process-lifetime ``startup_token``. Sessions and partitions stay
      in memory. A purged session drops its partition.
    - streamable-http: request-scoped Bearer auth. Sessions and partitions stay
      in memory unless ``PERFECTO_STORAGE_API_BASE_URL`` points at the storage
      service, which then owns ``/sessions`` and ``/session-partitions``.
    """
    storage, cache, storage_base_url, caller_token = _build_storage_and_cache(transport)
    sessions = _sessions_for(transport, storage, storage_base_url, caller_token)
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
            storage=storage,
            scope_resolver=DefaultSessionScopeResolver(),
            cache=cache,
            sessions=sessions,
        )

    if transport == "streamable-http":
        return AppRuntime(
            transport=transport,
            auth=HttpAuthProvider(),
            user_config={},
            storage=storage,
            scope_resolver=DefaultSessionScopeResolver(),
            cache=cache,
            sessions=sessions,
        )

    raise ValueError(f"Unknown transport: {transport}")
