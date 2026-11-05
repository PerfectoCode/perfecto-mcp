"""Chat session registry and the tool gate that requires session_id."""
import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from config.call_scope import user_id_for_token
from config.ids import SIMPLE_ID_ALPHABET
from config.runtime import build_runtime
from config.session import (
    SESSION_ID_PREFIX,
    SESSION_TOOL_NAME,
    HttpSessionProvider,
    InMemorySessionProvider,
    SessionError,
    SessionErrorCode,
    SessionState,
    generate_session_id,
    is_valid_session_id,
)
from config.session_context import (
    Identity,
    SessionContextMissing,
    bind_session_context,
    current_identity,
    current_session,
)
from config.storage import InMemorySessionStorageProvider, SessionPartitionPayload, SessionScope
from config.token import PerfectoToken
from models.result import BaseResult
from tests.conftest import make_ctx
from tools.dataframe_manager import list_dataframes_metadata, register_dataframe
from tools.runtime_tools import run_tool_with_runtime
from tools.session_gate import SESSION_HINT
from tools.session_manager import SessionManager, register as register_session_tool
from tools.utils import normalize_action_args

ALICE = PerfectoToken("alice-token", "demo")
BOB = PerfectoToken("bob-token", "demo")
ALICE_OTHER_CLOUD = PerfectoToken("alice-token", "other")


class _Clock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def _provider(clock, purged=None, idle=100, grace=10):
    return InMemorySessionProvider(
        idle_timeout_seconds=idle,
        purge_grace_seconds=grace,
        sweep_interval_seconds=1,
        on_purge=(lambda owner, sid: purged.append((owner, sid))) if purged is not None else None,
        clock=clock,
    )


def test_keep_alive_postpones_idle_expiry():
    clock = _Clock()
    provider = _provider(clock)

    async def scenario():
        session = await provider.open("alice", "secret")
        clock.advance(90)
        await provider.touch(session.session_id, "alice", "secret")
        clock.advance(90)
        touched = await provider.touch(session.session_id, "alice", "secret")
        assert touched.state is SessionState.ACTIVE

    asyncio.run(scenario())


def test_idle_session_expires_then_purges_after_the_grace_with_its_partition():
    clock = _Clock()
    purged = []
    provider = _provider(clock, purged)

    async def scenario():
        session = await provider.open("alice", "secret")
        clock.advance(100)
        await provider.open("bob", "other")
        clock.advance(8)
        with pytest.raises(SessionError) as expired:
            await provider.touch(session.session_id, "alice", "secret")
        assert expired.value.code is SessionErrorCode.EXPIRED
        assert purged == []

        clock.advance(10)
        with pytest.raises(SessionError) as gone:
            await provider.touch(session.session_id, "alice", "secret")
        assert gone.value.code is SessionErrorCode.INVALID
        assert purged == [("alice", session.session_id)]

    asyncio.run(scenario())


def test_stdio_runtime_releases_the_partition_of_a_purged_session():
    runtime = build_runtime("stdio", startup_token=ALICE)
    scope = SessionScope(user_id="alice", mcp_session_id="pfs_" + "a" * 32)

    async def scenario():
        await runtime.storage.put_partition(scope, SessionPartitionPayload(metadata={"x": 1}))
        runtime.sessions._on_purge("alice", scope.mcp_session_id)
        assert await runtime.storage.get_partition(scope) is None

    asyncio.run(scenario())


def test_session_ids_use_the_shared_alphabet():
    session_id = generate_session_id()
    assert session_id.startswith(SESSION_ID_PREFIX)
    assert set(session_id[len(SESSION_ID_PREFIX):]) <= set(SIMPLE_ID_ALPHABET)
    assert is_valid_session_id(session_id)
    for ambiguous in "ilou":
        assert not is_valid_session_id(SESSION_ID_PREFIX + ambiguous * 32)


def _http_provider(handler):
    return HttpSessionProvider(
        "https://storage.internal", "caller", transport=httpx.MockTransport(handler)
    )


@pytest.mark.parametrize("status,code", [(404, SessionErrorCode.INVALID), (410, SessionErrorCode.EXPIRED)])
def test_http_session_touch_keeps_invalid_and_expired(status, code):
    provider = _http_provider(lambda request: httpx.Response(status))
    with pytest.raises(SessionError) as failed:
        asyncio.run(provider.touch("pfs_" + "a" * 32, "alice", "secret"))
    assert failed.value.code is code


def test_http_provider_maps_storage_api_contract():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        record = {
            "id": "pfs_" + "b" * 32,
            "owner_id": body["owner_id"],
            "state": "ACTIVE",
            "created_at": "2026-09-01T00:00:00+00:00",
            "last_seen_at": "2026-09-01T00:00:00+00:00",
            "expired_at": None,
        }
        if request.url.path == "/sessions":
            return httpx.Response(201, json=record)
        if "unknown" in body["owner_id"]:
            return httpx.Response(404, json={"detail": "Session not found."})
        if "expired" in body["owner_id"]:
            return httpx.Response(410, json={"detail": "Session expired."})
        return httpx.Response(200, json=record)

    provider = HttpSessionProvider("http://storage", "mcp-caller", transport=httpx.MockTransport(handler))

    async def scenario():
        opened = await provider.open("owner-alice", "secret")
        assert opened.session_id == "pfs_" + "b" * 32
        assert (await provider.touch(opened.session_id, "owner-alice", "secret")).owner_id == "owner-alice"
        for owner, code in (("unknown-user", SessionErrorCode.INVALID), ("expired-user", SessionErrorCode.EXPIRED)):
            with pytest.raises(SessionError) as failed:
                await provider.touch(opened.session_id, owner, "secret")
            assert failed.value.code is code

    asyncio.run(scenario())
    assert all(request.headers["authorization"] == "Bearer mcp-caller" for request in requests)
    assert all(request.headers["x-perfecto-credential"] == "secret" for request in requests)
    assert requests[1].url.path == f"/sessions/{'pfs_' + 'b' * 32}/touch"


class _TokenAuth:
    def __init__(self):
        self.token = None

    def get_token(self, ctx):
        return self.token


class _FakeMcp:
    def __init__(self):
        self.tools = {}
        self.descriptions = {}

    def tool(self, *, name, description):
        def decorator(fn):
            self.tools[name] = fn
            self.descriptions[name] = description
            return fn
        return decorator


@pytest.fixture
def harness():
    auth = _TokenAuth()
    storage = InMemorySessionStorageProvider()
    sessions = InMemorySessionProvider(on_purge=storage.discard_session)
    runtime = replace(
        build_runtime("stdio", startup_token=ALICE),
        auth=auth,
        storage=storage,
        sessions=sessions,
    )
    mcp = _FakeMcp()
    register_session_tool(mcp, runtime)
    seen = []

    @mcp.tool(name="probe", description="Probe tool.")
    async def probe(arguments=None, ctx=None):
        action, args = normalize_action_args(arguments)
        runtime.configure_context(ctx)

        async def _dispatch():
            match action:
                case "whoami":
                    seen.append((current_identity(), current_session()))
                    return BaseResult(result=[{"ok": True}])
                case "store":
                    from config.storage import resolve_session_scope
                    scope = resolve_session_scope()
                    await register_dataframe(
                        result=[{"row": 1}],
                        origin_manager="probe",
                        origin_action="store",
                        json_size_chars=10,
                        session_storage=storage,
                        scope=scope,
                    )
                    return BaseResult(result=[{"stored": True}])
                case "count":
                    from config.storage import resolve_session_scope
                    listed = await list_dataframes_metadata(storage, resolve_session_scope())
                    return BaseResult(result=[{"dataframes": len(listed)}])
                case "batch":
                    return await mcp.tools["probe"](
                        {"action": "whoami", "args": args.get("sub_args", {})},
                        ctx,
                    )
            return BaseResult(error="unknown")

        return await run_tool_with_runtime(
            runtime, "probe", action, ctx, _dispatch, tool_args=args,
        )

    def call(tool, action, token, **args):
        auth.token = token
        result = asyncio.run(mcp.tools[tool](
            {"action": action, "args": args},
            make_ctx(token),
        ))
        return result.model_dump()

    def open_session(token=ALICE):
        body = call(SESSION_TOOL_NAME, "get", token)
        return body["session_id"]

    return {
        "call": call,
        "open_session": open_session,
        "sessions": sessions,
        "seen": seen,
        "mcp": mcp,
    }


def test_session_tool_returns_a_new_session_for_the_caller(harness):
    body = harness["call"](SESSION_TOOL_NAME, "get", ALICE)
    assert body.get("error") is None
    assert is_valid_session_id(body["session_id"])
    assert body["result"][0]["session_id"] == body["session_id"]
    assert harness["open_session"]() != body["session_id"]


def test_session_tool_rejects_a_missing_token(harness):
    body = harness["call"](SESSION_TOOL_NAME, "get", None)
    assert "Perfecto Security Token not set" in body["error"]
    assert "session_id" not in body


def test_missing_session_id_is_required_and_points_to_the_session_tool(harness):
    body = harness["call"]("probe", "whoami", ALICE)
    assert body["error_code"] == SessionErrorCode.REQUIRED.value
    assert SESSION_TOOL_NAME in body["error"]
    assert harness["seen"] == []


@pytest.mark.parametrize("bad", ["abc", "pfs_short", "PFS_" + "a" * 32, 123])
def test_malformed_session_id_is_invalid(harness, bad):
    body = harness["call"]("probe", "whoami", ALICE, session_id=bad)
    assert body["error_code"] == SessionErrorCode.INVALID.value


def test_unknown_and_foreign_sessions_are_indistinguishable(harness):
    alice_session = harness["open_session"](ALICE)
    foreign = harness["call"]("probe", "whoami", BOB, session_id=alice_session)
    unknown = harness["call"]("probe", "whoami", BOB, session_id="pfs_" + "0" * 32)
    other_cloud = harness["call"]("probe", "whoami", ALICE_OTHER_CLOUD, session_id=alice_session)
    assert foreign["error_code"] == unknown["error_code"] == other_cloud["error_code"] == SessionErrorCode.INVALID.value
    assert foreign["error"] == unknown["error"] == other_cloud["error"]
    assert harness["seen"] == []


def test_valid_session_binds_context_and_echoes_session_id(harness):
    session_id = harness["open_session"]()
    body = harness["call"]("probe", "whoami", ALICE, session_id=session_id)
    assert body.get("error") is None
    assert body["session_id"] == session_id
    identity, session = harness["seen"][0]
    assert identity.user_id == user_id_for_token(ALICE)
    assert session.session_id == session_id
    assert current_identity() is None and current_session() is None


def test_sessions_of_the_same_credential_do_not_share_dataframes(harness):
    first = harness["open_session"]()
    second = harness["open_session"]()
    harness["call"]("probe", "store", ALICE, session_id=first)
    assert harness["call"]("probe", "count", ALICE, session_id=first)["result"][0]["dataframes"] == 1
    assert harness["call"]("probe", "count", ALICE, session_id=second)["result"][0]["dataframes"] == 0


def test_nested_calls_inherit_the_session_and_reject_another_one(harness):
    session_id = harness["open_session"]()
    inherited = harness["call"]("probe", "batch", ALICE, session_id=session_id)
    assert inherited.get("error") is None
    assert harness["seen"][-1][1].session_id == session_id

    other = harness["open_session"]()
    body = harness["call"]("probe", "batch", ALICE, session_id=session_id, sub_args={"session_id": other})
    assert body["error_code"] == SessionErrorCode.INVALID.value


def test_session_tool_description_says_to_call_it_once(harness):
    assert "ONCE" in harness["mcp"].descriptions[SESSION_TOOL_NAME]
    assert SESSION_HINT not in harness["mcp"].descriptions[SESSION_TOOL_NAME]


def test_session_tool_reports_an_outage_without_a_traceback():
    class _Broken:
        async def open(self, owner_id, credential):
            raise RuntimeError("boom")

        async def touch(self, session_id, owner_id, credential):
            raise RuntimeError("boom")

    async def scenario():
        with bind_session_context(Identity(user_id="alice"), None, "secret"):
            return await SessionManager(_Broken()).get()

    result = asyncio.run(scenario())
    assert result.error_code == SessionErrorCode.UNAVAILABLE.value
    assert "Traceback" not in result.error
    assert "boom" not in result.error


def test_missing_identity_on_get_fails_closed():
    with pytest.raises(SessionContextMissing):
        asyncio.run(SessionManager(InMemorySessionProvider()).get())
