"""Session dataframes, async tasks and the method cache ported from BlazeMeter MCP."""
import asyncio
from types import SimpleNamespace

from config.call_scope import resolve_mcp_session_id, user_id_for_token
from config.runtime import build_runtime
from config.session_context import bind_call_scope
from config.storage import InMemorySessionStorageProvider, SessionScope
from config.token import PerfectoToken
from models.manager import Manager
from models.result import BaseResult, PaginationResult
from tools.async_task_manager import configure_task_storage, get_task_record
from tools.data_tools import DataTools
from tools.dataframe_manager import finalize_tool_result, query_dataframes
from tools.method_cache import ttl_cache_method
from tools.task_runtime import run_as_task


def _scope(user_id: str, session_id: str = "local") -> SessionScope:
    return SessionScope(user_id=user_id, mcp_session_id=session_id)


def test_user_and_session_scope_are_stable_and_separated():
    demo = PerfectoToken("token-a", "demo")
    other_cloud = PerfectoToken("token-a", "other")
    other_token = PerfectoToken("token-b", "demo")

    assert user_id_for_token(demo) == user_id_for_token(PerfectoToken("token-a", "demo"))
    assert user_id_for_token(demo) != user_id_for_token(other_cloud)
    assert user_id_for_token(demo) != user_id_for_token(other_token)
    assert user_id_for_token(None) == "anonymous"
    assert resolve_mcp_session_id(None) == "local"
    assert resolve_mcp_session_id(SimpleNamespace(session_id="sess-1")) == "sess-1"
    request = SimpleNamespace(headers={"mcp-session-id": "from-header"})
    ctx = SimpleNamespace(session_id="from-ctx", request_context=SimpleNamespace(request=request))
    assert resolve_mcp_session_id(ctx) == "from-header"


def test_large_results_become_dataframes_and_stay_session_scoped():
    async def scenario():
        storage = InMemorySessionStorageProvider()
        left = _scope("user-a", "s1")
        right = _scope("user-b", "s1")
        small = await finalize_tool_result(
            BaseResult(result=[{"id": 1}]),
            action="list_real_devices",
            args={"result_format": "auto"},
            origin_manager="perfecto_devices",
            session_storage=storage,
            scope=left,
        )
        assert small.result == [{"id": 1}]

        rows = [{"id": index, "name": f"device-{index}", "pad": "x" * 40} for index in range(200)]
        stored = await finalize_tool_result(
            BaseResult(result=rows),
            action="list_real_devices",
            args={},
            origin_manager="perfecto_devices",
            session_storage=storage,
            scope=left,
        )
        assert stored.result[0]["stored_as_dataframe"] is True
        table = stored.result[0]["table_name"]

        paged = await finalize_tool_result(
            BaseResult(result=PaginationResult(items=rows, count=len(rows), total=len(rows), has_more=False)),
            action="list_report_executions",
            args={"result_format": "dataframe"},
            origin_manager="perfecto_execution",
            session_storage=storage,
            scope=left,
        )
        assert paged.result[0]["stored_as_dataframe"] is True

        raw = await finalize_tool_result(
            BaseResult(result=rows),
            action="list_real_devices",
            args={"result_format": "raw"},
            origin_manager="perfecto_devices",
            session_storage=storage,
            scope=left,
        )
        assert raw.result == rows

        queried = await query_dataframes(
            f"SELECT id, name FROM {table} ORDER BY id LIMIT 2 OFFSET 1",
            session_storage=storage,
            scope=left,
            output_format="records",
        )
        assert queried.get("error") is None
        assert queried["result"] == [
            {"id": 1, "name": "device-1"},
            {"id": 2, "name": "device-2"},
        ]

        other = await query_dataframes(
            f"SELECT id FROM {table} ORDER BY id LIMIT 1 OFFSET 0",
            session_storage=storage,
            scope=right,
            output_format="records",
        )
        assert other.get("error")

        blocked = await query_dataframes(
            f"DELETE FROM {table}",
            session_storage=storage,
            scope=left,
        )
        assert blocked.get("error")

    asyncio.run(scenario())


def test_fast_task_returns_result_and_slow_task_returns_a_snapshot():
    async def scenario():
        storage = InMemorySessionStorageProvider()
        configure_task_storage(storage)
        scope = _scope("user-a", "local")

        class Work(Manager):
            @run_as_task(fast_response_threshold_seconds=1)
            async def quick(self):
                return BaseResult(result=[{"done": True}])

            @run_as_task(fast_response_threshold_seconds=0.05)
            async def slow(self):
                await asyncio.sleep(0.3)
                return BaseResult(result=[{"done": True}])

        ctx = SimpleNamespace()
        worker = Work(ctx)
        with bind_call_scope(scope.user_id, scope.mcp_session_id):
            quick = await worker.quick()
            assert quick.result == [{"done": True}]
            assert await get_task_record("missing", scope=scope) is None

            pending = await worker.slow()
        assert pending.pending_task is not None
        task_id, task_scope = pending.pending_task
        assert task_scope == scope
        assert pending.result[0]["task_id"] == task_id
        assert pending.result[0]["status"] in {"parking", "working"}

        record = await get_task_record(task_id, scope=scope)
        assert record is not None
        await asyncio.wait_for(record.asyncio_task, timeout=2)
        finished = await get_task_record(task_id, scope=scope)
        assert finished.status == "completed"
        assert finished.result.result == [{"done": True}]

        tools = DataTools(ctx, storage, scope_resolver=_FixedScope(scope))
        status = await tools.tasks_status(task_id)
        assert status.error is None
        assert status.result[0]["status"] == "completed"
        fetched = await tools.tasks_get(task_id)
        assert fetched.result[0]["task_result"]["result"] == [{"done": True}]
        missing = await tools.tasks_get(task_id)
        assert missing.error

    asyncio.run(scenario())


def test_method_cache_reuses_user_scoped_results():
    async def scenario():
        calls = {"n": 0}

        class Reader:
            def __init__(self, token):
                self.token = token

            @ttl_cache_method(ttl_seconds=30)
            async def read(self):
                calls["n"] += 1
                return BaseResult(result=[{"n": calls["n"]}])

        reader = Reader(PerfectoToken("token-a", "demo"))
        with bind_call_scope(user_id_for_token(reader.token), "local", reader.token.token):
            first = await reader.read()
            second = await reader.read()
        assert first.result == [{"n": 1}]
        assert second.result == [{"n": 1}]
        assert calls["n"] == 1

        anonymous = Reader(None)
        with bind_call_scope("anonymous", "local"):
            await anonymous.read()
            await anonymous.read()
        assert calls["n"] == 3

    asyncio.run(scenario())


def test_runtime_uses_memory_until_a_storage_url_is_configured(monkeypatch):
    monkeypatch.delenv("PERFECTO_STORAGE_API_BASE_URL", raising=False)
    monkeypatch.delenv("PERFECTO_MCP_STORAGE_CALLER_TOKEN", raising=False)
    runtime = build_runtime("stdio", startup_token=PerfectoToken("token-a", "demo"))
    assert runtime.storage.__class__.__name__ == "InMemorySessionStorageProvider"
    assert runtime.sessions.__class__.__name__ == "InMemorySessionProvider"
    assert runtime.cache.__class__.__name__ == "InMemoryTTLCache"

    http_runtime = build_runtime("streamable-http")
    assert http_runtime.storage.__class__.__name__ == "InMemorySessionStorageProvider"
    assert http_runtime.sessions.__class__.__name__ == "InMemorySessionProvider"

    monkeypatch.setenv("PERFECTO_STORAGE_API_BASE_URL", "http://storage.internal")
    try:
        build_runtime("streamable-http")
        raised = False
    except ValueError as exc:
        raised = True
        assert "PERFECTO_MCP_STORAGE_CALLER_TOKEN" in str(exc)
    assert raised


class _FixedScope:
    def __init__(self, scope: SessionScope):
        self._scope = scope

    def resolve(self) -> SessionScope:
        return self._scope
