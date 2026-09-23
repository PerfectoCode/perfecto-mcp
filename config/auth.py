"""Per-request authentication for the streamable HTTP transport."""
from __future__ import annotations

import os
from typing import Optional, Protocol, runtime_checkable

from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from config.perfecto import PERFECTO_CLOUD_NAME_ENV_NAME
from config.token import PerfectoToken, PerfectoTokenError

PERFECTO_TOKEN_STATE_ATTR = "token"
PERFECTO_USER_CONFIG_STATE_ATTR = "user_config"
PERFECTO_CLOUD_NAME_HEADER = "perfecto-cloud-name"

# Unauthenticated probe paths for orchestrators / load balancers.
HEALTH_PATHS = frozenset({"/health", "/healthz"})


class AuthError(Exception):
    """Raised when Authorization cannot be parsed into credentials."""


@runtime_checkable
class AuthPort(Protocol):
    """Resolves the Perfecto security token for the current tool invocation."""

    def get_token(self, ctx: Context) -> Optional[PerfectoToken]:
        ...


class StdioAuthProvider:
    """Process-lifetime token from env / token file / Docker secrets."""

    def __init__(self, token: Optional[PerfectoToken]):
        self._token = token

    def get_token(self, ctx: Context) -> Optional[PerfectoToken]:
        return self._token


class HttpAuthProvider:
    """Per-request token attached by Bearer auth middleware to request.state."""

    def get_token(self, ctx: Context) -> Optional[PerfectoToken]:
        request = ctx.request_context.request
        if request is None:
            return None
        return getattr(request.state, PERFECTO_TOKEN_STATE_ATTR, None)


def resolve_cloud_name(header_value: Optional[str] = None) -> Optional[str]:
    """
    Resolve the Perfecto cloud for a request.

    Precedence: ``Perfecto-Cloud-Name`` header > PERFECTO_CLOUD_NAME env var.
    """
    candidate = (header_value or "").strip()
    if candidate:
        return candidate
    return os.getenv(PERFECTO_CLOUD_NAME_ENV_NAME, "").strip() or None


def parse_authorization_header(value: Optional[str], cloud_name: Optional[str] = None) -> PerfectoToken:
    """
    Parse ``Authorization: Bearer <security-token>`` into a PerfectoToken.

    The cloud name is not carried in the credentials; it comes from the
    ``Perfecto-Cloud-Name`` header or PERFECTO_CLOUD_NAME. Does not call the
    Perfecto API — parse only.
    """
    if not value or not value.strip():
        raise AuthError("Missing Authorization header")

    scheme, _, credentials = value.strip().partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        raise AuthError("Authorization header must use Bearer scheme")

    try:
        return PerfectoToken.from_bearer_credentials(credentials.strip(), cloud_name)
    except PerfectoTokenError as exc:
        raise AuthError("Unparseable Bearer credentials") from exc


class BearerAuthMiddleware:
    """
    HTTP gate: require a parseable Bearer token on every request.

    Attaches PerfectoToken to ``request.state``; does not validate against Perfecto.
    A missing cloud name is not rejected here — tools surface it as a
    configuration error, the same way stdio does.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "") or ""
        if path in HEALTH_PATHS:
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        cloud_name = resolve_cloud_name(request.headers.get(PERFECTO_CLOUD_NAME_HEADER))
        try:
            token = parse_authorization_header(
                request.headers.get("authorization"),
                cloud_name,
            )
        except AuthError:
            response = JSONResponse(
                {"error": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        setattr(request.state, PERFECTO_TOKEN_STATE_ATTR, token)
        setattr(
            request.state,
            PERFECTO_USER_CONFIG_STATE_ATTR,
            {"token": token, "cloud_name": token.cloud_name},
        )
        await self.app(scope, receive, send)


def register_health_routes(mcp: FastMCP) -> None:
    """Register unauthenticated health probes on the FastMCP ASGI app."""

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})


def run_streamable_http(mcp: FastMCP) -> None:
    """Serve FastMCP over streamable HTTP with Bearer auth middleware."""
    import anyio
    import uvicorn

    register_health_routes(mcp)

    async def _serve() -> None:
        app = BearerAuthMiddleware(mcp.streamable_http_app())
        config = uvicorn.Config(
            app,
            host=mcp.settings.host,
            port=mcp.settings.port,
            log_level=mcp.settings.log_level.lower(),
        )
        await uvicorn.Server(config).serve()

    anyio.run(_serve)
