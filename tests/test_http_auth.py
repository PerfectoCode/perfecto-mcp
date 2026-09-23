"""
Copyright 2025 Perforce Software, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from config.auth import (
    AuthError,
    PERFECTO_CLOUD_NAME_HEADER,
    PERFECTO_TOKEN_STATE_ATTR,
    PERFECTO_USER_CONFIG_STATE_ATTR,
    BearerAuthMiddleware,
    HttpAuthProvider,
    StdioAuthProvider,
    parse_authorization_header,
    resolve_cloud_name,
)
from config.perfecto import PERFECTO_CLOUD_NAME_ENV_NAME
from config.runtime import build_runtime
from config.token import PerfectoToken, PerfectoTokenError
from models.manager import Manager


class TestBearerCredentialParsing:
    def test_security_token_with_cloud_name(self):
        token = PerfectoToken.from_bearer_credentials("security-token", "demo")
        assert token.token == "security-token"
        assert token.cloud_name == "demo"

    def test_security_token_without_cloud_name(self):
        token = PerfectoToken.from_bearer_credentials("security-token")
        assert token.token == "security-token"
        assert token.cloud_name is None

    def test_blank_cloud_name_is_normalized_to_none(self):
        token = PerfectoToken.from_bearer_credentials("security-token", "   ")
        assert token.cloud_name is None

    def test_empty_raises(self):
        with pytest.raises(PerfectoTokenError):
            PerfectoToken.from_bearer_credentials("  ")


class TestResolveCloudName:
    def test_header_wins_over_env(self, monkeypatch):
        monkeypatch.setenv(PERFECTO_CLOUD_NAME_ENV_NAME, "env-cloud")
        assert resolve_cloud_name("header-cloud") == "header-cloud"

    def test_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv(PERFECTO_CLOUD_NAME_ENV_NAME, "env-cloud")
        assert resolve_cloud_name(None) == "env-cloud"
        assert resolve_cloud_name("  ") == "env-cloud"

    def test_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv(PERFECTO_CLOUD_NAME_ENV_NAME, raising=False)
        assert resolve_cloud_name(None) is None


class TestAuthorizationHeaderParsing:
    def test_bearer_security_token(self):
        token = parse_authorization_header("Bearer security-token", "demo")
        assert token.token == "security-token"
        assert token.cloud_name == "demo"

    def test_missing_header(self):
        with pytest.raises(AuthError):
            parse_authorization_header(None)

    def test_wrong_scheme(self):
        with pytest.raises(AuthError):
            parse_authorization_header("Basic abc")

    def test_bearer_without_credentials(self):
        with pytest.raises(AuthError):
            parse_authorization_header("Bearer    ")


class TestAuthProviders:
    def test_stdio_returns_startup_token(self, perfecto_token):
        provider = StdioAuthProvider(perfecto_token)
        assert provider.get_token(ctx=None) is perfecto_token

    def test_stdio_allows_none(self):
        assert StdioAuthProvider(None).get_token(ctx=None) is None

    def test_http_reads_request_state(self):
        token_a = PerfectoToken("token-a", "cloud-a")
        token_b = PerfectoToken("token-b", "cloud-b")
        provider = HttpAuthProvider()

        def ctx_with(token: PerfectoToken):
            request = SimpleNamespace(state=SimpleNamespace(**{PERFECTO_TOKEN_STATE_ATTR: token}))
            request_context = SimpleNamespace(request=request)
            return SimpleNamespace(request_context=request_context)

        assert provider.get_token(ctx_with(token_a)).cloud_name == "cloud-a"
        assert provider.get_token(ctx_with(token_b)).cloud_name == "cloud-b"

    def test_http_concurrent_tokens_are_isolated(self):
        """Two contexts with different Bearer-derived tokens resolve independently."""
        provider = HttpAuthProvider()
        token_a = PerfectoToken("token-a", "cloud-a")
        token_b = PerfectoToken("token-b", "cloud-b")

        def make_request_ctx(token: PerfectoToken):
            request = MagicMock()
            setattr(request.state, PERFECTO_TOKEN_STATE_ATTR, token)
            ctx = MagicMock()
            ctx.request_context.request = request
            return ctx

        assert provider.get_token(make_request_ctx(token_a)).token == "token-a"
        assert provider.get_token(make_request_ctx(token_b)).token == "token-b"


class TestManagerTokenResolution:
    def test_manager_falls_back_to_request_state_token(self, perfecto_token):
        request = SimpleNamespace(state=SimpleNamespace(**{PERFECTO_TOKEN_STATE_ATTR: perfecto_token}))
        ctx = SimpleNamespace(request_context=SimpleNamespace(request=request))

        manager = Manager(ctx)

        assert manager.token is perfecto_token


class _StrictCtx:
    """Mimics FastMCP Context where arbitrary attrs are disallowed."""

    def __init__(self, request_context):
        object.__setattr__(self, "request_context", request_context)

    def __setattr__(self, name, value):
        if name == "user_config":
            raise ValueError('"Context" object has no field "user_config"')
        object.__setattr__(self, name, value)


class TestBearerAuthMiddleware:
    def _app(self):
        async def ok(request: Request):
            token = getattr(request.state, PERFECTO_TOKEN_STATE_ATTR, None)
            user_config = getattr(request.state, PERFECTO_USER_CONFIG_STATE_ATTR, {})
            return JSONResponse(
                {
                    "token": token.token if token else None,
                    "cloud_name": user_config.get("cloud_name"),
                }
            )

        return BearerAuthMiddleware(Starlette(routes=[Route("/mcp", endpoint=ok, methods=["POST"])]))

    def test_missing_authorization_returns_401(self):
        client = TestClient(self._app())
        response = client.post("/mcp")
        assert response.status_code == 401
        assert response.json()["error"] == "Unauthorized"
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_wrong_scheme_returns_401(self):
        client = TestClient(self._app())
        response = client.post("/mcp", headers={"Authorization": "Basic abc"})
        assert response.status_code == 401

    def test_valid_bearer_attaches_token(self, monkeypatch):
        monkeypatch.delenv(PERFECTO_CLOUD_NAME_ENV_NAME, raising=False)
        client = TestClient(self._app())
        response = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer security-token",
                PERFECTO_CLOUD_NAME_HEADER: "demo",
            },
        )
        assert response.status_code == 200
        assert response.json()["token"] == "security-token"
        assert response.json()["cloud_name"] == "demo"

    def test_cloud_name_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv(PERFECTO_CLOUD_NAME_ENV_NAME, "env-cloud")
        client = TestClient(self._app())
        response = client.post("/mcp", headers={"Authorization": "Bearer security-token"})
        assert response.status_code == 200
        assert response.json()["cloud_name"] == "env-cloud"

    def test_missing_cloud_name_is_not_rejected_at_the_gate(self, monkeypatch):
        """Tools surface the missing cloud as a config error, the same as stdio."""
        monkeypatch.delenv(PERFECTO_CLOUD_NAME_ENV_NAME, raising=False)
        client = TestClient(self._app())
        response = client.post("/mcp", headers={"Authorization": "Bearer security-token"})
        assert response.status_code == 200
        assert response.json()["cloud_name"] is None

    def test_cloud_name_not_persisted_between_requests(self, monkeypatch):
        monkeypatch.delenv(PERFECTO_CLOUD_NAME_ENV_NAME, raising=False)
        client = TestClient(self._app())
        first = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer security-token",
                PERFECTO_CLOUD_NAME_HEADER: "demo",
            },
        )
        assert first.json()["cloud_name"] == "demo"

        second = client.post("/mcp", headers={"Authorization": "Bearer security-token"})
        assert second.json()["cloud_name"] is None

    def test_options_bypasses_auth(self):
        async def ok(_request: Request):
            return JSONResponse({"ok": True})

        app = BearerAuthMiddleware(Starlette(routes=[Route("/mcp", endpoint=ok, methods=["OPTIONS"])]))
        client = TestClient(app)
        assert client.options("/mcp").status_code == 200

    def test_health_bypasses_auth(self):
        async def health(_request: Request):
            return JSONResponse({"status": "ok"})

        app = BearerAuthMiddleware(
            Starlette(
                routes=[
                    Route("/health", endpoint=health, methods=["GET"]),
                    Route("/healthz", endpoint=health, methods=["GET"]),
                ]
            )
        )
        client = TestClient(app)
        assert client.get("/health").status_code == 200
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/healthz").status_code == 200


class TestBuildRuntime:
    def test_build_runtime_stdio_and_http(self, perfecto_token):
        stdio = build_runtime("stdio", startup_token=perfecto_token)
        assert stdio.transport == "stdio"
        assert isinstance(stdio.auth, StdioAuthProvider)
        assert stdio.user_config["token"] is perfecto_token
        assert stdio.user_config["cloud_name"] == "demo"

        http = build_runtime("streamable-http")
        assert http.transport == "streamable-http"
        assert isinstance(http.auth, HttpAuthProvider)
        assert http.user_config == {}

    def test_unknown_transport_raises(self):
        with pytest.raises(ValueError, match="Unknown transport"):
            build_runtime("carrier-pigeon")

    def test_configure_context_injects_request_context_for_stdio(self, perfecto_token):
        runtime = build_runtime("stdio", startup_token=perfecto_token)
        ctx = SimpleNamespace(request_context=SimpleNamespace(request=None))

        user_config = runtime.configure_context(ctx)

        assert user_config["token"] is perfecto_token
        assert getattr(ctx.request_context, PERFECTO_USER_CONFIG_STATE_ATTR, None) == user_config
        assert Manager(ctx).token is perfecto_token

    def test_configure_context_merges_http_request_state(self):
        runtime = build_runtime("streamable-http")
        token = PerfectoToken("security-token", "demo")
        request = SimpleNamespace(
            state=SimpleNamespace(
                **{
                    PERFECTO_TOKEN_STATE_ATTR: token,
                    PERFECTO_USER_CONFIG_STATE_ATTR: {"token": token, "cloud_name": "demo"},
                }
            )
        )
        ctx = SimpleNamespace(request_context=SimpleNamespace(request=request))

        user_config = runtime.configure_context(ctx)

        assert user_config["token"] is token
        assert user_config["cloud_name"] == "demo"
        assert getattr(ctx.request_context, PERFECTO_USER_CONFIG_STATE_ATTR, None) == user_config
        assert getattr(request.state, PERFECTO_USER_CONFIG_STATE_ATTR, None) == user_config

    def test_configure_context_hydrates_request_context_when_ctx_is_strict(self):
        runtime = build_runtime("streamable-http")
        token = PerfectoToken("security-token", "demo")
        request = SimpleNamespace(
            state=SimpleNamespace(
                **{
                    PERFECTO_TOKEN_STATE_ATTR: token,
                    PERFECTO_USER_CONFIG_STATE_ATTR: {"token": token, "cloud_name": "demo"},
                }
            )
        )
        ctx = _StrictCtx(request_context=SimpleNamespace(request=request))

        user_config = runtime.configure_context(ctx)
        manager = Manager(ctx)

        assert user_config["token"] is token
        assert getattr(ctx.request_context, PERFECTO_USER_CONFIG_STATE_ATTR, None) == user_config
        assert manager.token is token

    def test_http_runtime_isolates_concurrent_sessions(self):
        """Each request context resolves only its own Bearer-derived token."""
        runtime = build_runtime("streamable-http")

        def ctx_for(token: PerfectoToken):
            request = SimpleNamespace(state=SimpleNamespace(**{PERFECTO_TOKEN_STATE_ATTR: token}))
            return SimpleNamespace(request_context=SimpleNamespace(request=request))

        token_a = PerfectoToken("token-a", "cloud-a")
        token_b = PerfectoToken("token-b", "cloud-b")
        ctx_a = ctx_for(token_a)
        ctx_b = ctx_for(token_b)

        runtime.configure_context(ctx_a)
        runtime.configure_context(ctx_b)

        assert Manager(ctx_a).token is token_a
        assert Manager(ctx_b).token is token_b
