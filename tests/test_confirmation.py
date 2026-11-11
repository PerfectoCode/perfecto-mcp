import asyncio
from types import SimpleNamespace

from models.result import BaseResult
from tests.conftest import make_ctx
from tools.ai_scriptless_manager import AiScriptlessManager
from tools.execution_manager import ExecutionManager
from tools.utils import (
    Confirmation,
    ConfirmMode,
    Operations,
    get_confirm_mode,
    operation_need_confirmation,
    register_confirm_mode,
    require_confirmation,
)


class _Gate:
    def __init__(self, ctx):
        self.ctx = ctx
        self.calls = 0

    @require_confirmation(operation=Operations.DELETE)
    async def delete(self):
        self.calls += 1
        return BaseResult(result="deleted")

    @require_confirmation(operation=Operations.CREATE)
    async def create(self):
        self.calls += 1
        return BaseResult(result="created")

    @require_confirmation(operation=Operations.UPDATE)
    async def update(self):
        self.calls += 1
        return BaseResult(result="updated")

    @require_confirmation(operation=Operations.READ)
    async def read(self):
        self.calls += 1
        return BaseResult(result="read")


def _ctx_with(elicit):
    ctx = SimpleNamespace()
    ctx.elicit = elicit
    return ctx


class TestOperationNeedConfirmation:
    def test_delete_mode_confirms_deletes_only(self):
        register_confirm_mode(ConfirmMode.DELETE)

        assert operation_need_confirmation(Operations.DELETE) is True
        assert operation_need_confirmation(Operations.CREATE) is False
        assert operation_need_confirmation(Operations.UPDATE) is False
        assert operation_need_confirmation(Operations.READ) is False

    def test_cud_mode_confirms_mutations_only(self):
        register_confirm_mode(ConfirmMode.CUD)

        assert operation_need_confirmation(Operations.CREATE) is True
        assert operation_need_confirmation(Operations.UPDATE) is True
        assert operation_need_confirmation(Operations.DELETE) is True
        assert operation_need_confirmation(Operations.READ) is False

    def test_disable_mode_confirms_nothing(self):
        register_confirm_mode(ConfirmMode.DISABLE)

        assert get_confirm_mode() is ConfirmMode.DISABLE
        assert operation_need_confirmation(Operations.DELETE) is False
        assert operation_need_confirmation(Operations.CREATE) is False
        assert operation_need_confirmation(Operations.UPDATE) is False


class TestRequireConfirmation:
    def test_accept_runs_the_operation(self):
        seen = {}

        async def elicit(message, schema):
            seen["message"] = message
            seen["schema"] = schema
            return SimpleNamespace(action="accept", data=schema())

        gate = _Gate(_ctx_with(elicit))
        result = asyncio.run(gate.delete())

        assert result.result == "deleted"
        assert gate.calls == 1
        assert seen["schema"] is Confirmation
        assert seen["message"] == "This action requires manual confirmation to continue"

    def test_decline_or_cancel_does_not_run_the_operation(self):
        async def elicit(message, schema):
            return SimpleNamespace(action="decline", data=None)

        gate = _Gate(_ctx_with(elicit))
        result = asyncio.run(gate.delete())

        assert gate.calls == 0
        assert result.error is None
        assert result.result == ["Action manually cancelled by the user."]

    def test_accept_without_data_does_not_run_the_operation(self):
        async def elicit(message, schema):
            return SimpleNamespace(action="accept", data=None)

        gate = _Gate(_ctx_with(elicit))
        result = asyncio.run(gate.delete())

        assert gate.calls == 0
        assert result.result == ["Action manually cancelled by the user."]

    def test_client_without_elicitation_fails_closed(self):
        gate = _Gate(SimpleNamespace())
        result = asyncio.run(gate.delete())

        assert gate.calls == 0
        assert result.result is None
        assert "does not support elicitation" in result.error

    def test_delete_mode_does_not_prompt_for_create_or_read(self):
        async def elicit(message, schema):
            raise AssertionError("elicit should not be called")

        gate = _Gate(_ctx_with(elicit))

        assert asyncio.run(gate.create()).result == "created"
        assert asyncio.run(gate.read()).result == "read"
        assert gate.calls == 2

    def test_cud_mode_prompts_for_update(self):
        register_confirm_mode(ConfirmMode.CUD)

        async def elicit(message, schema):
            return SimpleNamespace(action="cancel", data=None)

        gate = _Gate(_ctx_with(elicit))
        result = asyncio.run(gate.update())

        assert gate.calls == 0
        assert result.result == ["Action manually cancelled by the user."]

    def test_disable_mode_skips_the_prompt_for_delete(self):
        register_confirm_mode(ConfirmMode.DISABLE)

        async def elicit(message, schema):
            raise AssertionError("elicit should not be called")

        gate = _Gate(_ctx_with(elicit))

        assert asyncio.run(gate.delete()).result == "deleted"
        assert gate.calls == 1


class TestManagerConfirmation:
    def test_delete_test_prompts_and_skips_the_api_when_declined(self, perfecto_token, monkeypatch):
        calls = {"n": 0}

        async def fake_api_request(*_args, **_kwargs):
            calls["n"] += 1
            return BaseResult(result={"status": "deleted"})

        monkeypatch.setattr("tools.ai_scriptless_manager.api_request", fake_api_request)
        manager = AiScriptlessManager(make_ctx(perfecto_token, elicit="decline"))

        result = asyncio.run(manager.delete_test("PRIVATE:Folder/Test.xml"))

        assert calls["n"] == 0
        assert result.result == ["Action manually cancelled by the user."]

    def test_delete_test_fails_closed_when_the_client_cannot_elicit(self, perfecto_token, monkeypatch):
        async def fake_api_request(*_args, **_kwargs):
            raise AssertionError("api should not be called")

        monkeypatch.setattr("tools.ai_scriptless_manager.api_request", fake_api_request)
        manager = AiScriptlessManager(make_ctx(perfecto_token, elicit="missing"))

        result = asyncio.run(manager.delete_test("PRIVATE:Folder/Test.xml"))

        assert "does not support elicitation" in result.error

    def test_create_test_runs_without_a_prompt_in_delete_mode(self, perfecto_token, monkeypatch):
        prompts = {"n": 0}

        async def elicit(message, schema):
            prompts["n"] += 1
            return SimpleNamespace(action="accept", data=schema())

        async def fake_persist(_token, item_key, script, saved_script=None, snapshot_comment=None):
            return BaseResult(result={"draft_key": "d-1", "status": "ok"})

        monkeypatch.setattr("tools.ai_scriptless_manager.persist_script", fake_persist)
        manager = AiScriptlessManager(make_ctx(perfecto_token, elicit=elicit))

        result = asyncio.run(manager.create_test("Login"))

        assert prompts["n"] == 0
        assert result.error is None

    def test_create_test_prompts_in_cud_mode(self, perfecto_token):
        register_confirm_mode(ConfirmMode.CUD)
        manager = AiScriptlessManager(make_ctx(perfecto_token, elicit="decline"))

        result = asyncio.run(manager.create_test("Login"))

        assert result.result == ["Action manually cancelled by the user."]

    def test_stop_live_executions_prompts_only_in_cud_mode(self, perfecto_token, monkeypatch):
        calls = {"n": 0}

        async def fake_api_request(*_args, **_kwargs):
            calls["n"] += 1
            return BaseResult(result={"stopped": True})

        monkeypatch.setattr("tools.execution_manager.api_request", fake_api_request)

        async def elicit(message, schema):
            raise AssertionError("elicit should not be called")

        manager = ExecutionManager(make_ctx(perfecto_token, elicit=elicit))
        result = asyncio.run(manager.stop_live_executions(["exec-1"]))

        assert calls["n"] == 1
        assert result.error is None

        register_confirm_mode(ConfirmMode.CUD)
        manager = ExecutionManager(make_ctx(perfecto_token, elicit="decline"))
        result = asyncio.run(manager.stop_live_executions(["exec-1"]))

        assert calls["n"] == 1
        assert result.result == ["Action manually cancelled by the user."]
