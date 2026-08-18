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

import asyncio
import copy
import inspect
import json

import httpx
import pytest

from config.perfecto import SUPPORT_MESSAGE
from models.result import BaseResult
from tools import ai_scriptless_manager
from tools.ai_scriptless import definitions
from tools.ai_scriptless.elements import (
    build_flow_element,
    build_if_statement,
    build_logical_step,
    new_empty_script,
)
from tools.ai_scriptless_manager import AiScriptlessManager, STEP_PATH_REFRESH_NOTES

TEST_ID = "PRIVATE:Folder/Test.xml"


def _tests_tree_response() -> dict:
    return {
        "items": [
            {
                "visibility": "PRIVATE",
                "items": [
                    {
                        "type": "CONTAINER",
                        "items": [
                            {
                                "type": "SIMPLE",
                                "key": "PRIVATE:My Folder/Login.xml",
                                "name": "Login.xml",
                                "createdBy": "alice",
                                "modifiedBy": "bob",
                                "creationTime": {"formatted": "2024-01-01"},
                                "modificationTime": {"formatted": "2024-01-02"},
                            },
                        ],
                    },
                ],
            },
        ],
    }


def _script_payload() -> dict:
    script = new_empty_script()
    script["flowElements"] = [build_flow_element("wait")]
    return {"script": script, "commandDefinitions": []}


def _script_with_logical_group() -> dict:
    group = build_logical_step("Setup")
    group["flowElements"] = []
    script = new_empty_script()
    script["flowElements"] = [group]
    script["numOfFlowElements"] = 1
    return script


def _script_with_steps(*command_ids: str) -> dict:
    script = new_empty_script()
    script["flowElements"] = [build_flow_element(command_id) for command_id in command_ids]
    script["numOfFlowElements"] = len(script["flowElements"])
    return script


def _mock_load_and_mutate(monkeypatch, initial_script: dict | None = None, captured: dict | None = None):
    base_script = copy.deepcopy(initial_script or new_empty_script())

    async def fake_load_and_mutate(_token, test_id, mutator, snapshot_comment=None):
        script = copy.deepcopy(base_script)
        try:
            outcome = mutator(script)
            if inspect.isawaitable(outcome):
                await outcome
        except ValueError as exc:
            return BaseResult(error=str(exc))
        if captured is not None:
            captured["script"] = script
            captured["test_id"] = test_id
            captured["snapshot_comment"] = snapshot_comment
        return BaseResult(result={"item_key": test_id, "draft_key": "draft-1", "status": "ok"})

    monkeypatch.setattr(ai_scriptless_manager, "load_and_mutate", fake_load_and_mutate)


def _assert_step_path_notes(result: BaseResult) -> None:
    assert result.error is None
    for note in STEP_PATH_REFRESH_NOTES:
        assert note in result.result["notes"]


class TestExecuteTestDeviceMapping:
    def test_real_device_accepts_snake_case_device_id(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            captured["json"] = kwargs.get("json")
            return BaseResult(result={"executionId": "exec-1"})

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.execute_test(
            "PRIVATE:Folder/Test.xml",
            "real",
            {"device_id": "DEVICE-123"},
        ))

        assert result.error is None
        assert captured["json"]["params"]["DUT"] == "DEVICE-123"
        assert captured["json"]["testKey"] == "PRIVATE:Folder/Test.xml"

    def test_real_device_accepts_perfecto_device_id_key(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            captured["json"] = kwargs.get("json")
            return BaseResult(result={"executionId": "exec-1"})

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.execute_test(
            "PRIVATE:Folder/Test.xml",
            "real",
            {"deviceId": "DEVICE-456"},
        ))

        assert result.error is None
        assert captured["json"]["params"]["DUT"] == "DEVICE-456"

    def test_real_device_requires_device_id(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.execute_test(
            "PRIVATE:Folder/Test.xml",
            "real",
            {},
        ))
        assert "device_id could not be found" in result.error

    def test_virtual_device_serializes_capabilities_json(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            captured["json"] = kwargs.get("json")
            return BaseResult(result={"executionId": "exec-2"})

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.execute_test(
            "PRIVATE:Folder/Test.xml",
            "virtual",
            {
                "platform_name": "Android",
                "manufacturer": "Google",
                "model": "Pixel 8",
                "platform_version": "14",
            },
        ))

        assert result.error is None
        dut = json.loads(captured["json"]["params"]["DUT"])
        assert dut["platformName"] == "Android"
        assert dut["manufacturer"] == "Google"

    def test_virtual_device_sends_null_for_unspecified_capabilities(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            captured["json"] = kwargs.get("json")
            return BaseResult(result={"executionId": "exec-3"})

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.execute_test(
            "PRIVATE:Folder/Test.xml",
            "virtual",
            {"platform_name": "Android"},
        ))

        assert result.error is None
        dut = json.loads(captured["json"]["params"]["DUT"])
        assert dut["platformName"] == "Android"
        assert dut["manufacturer"] is None
        assert dut["model"] is None

    def test_invalid_device_type_returns_error(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.execute_test(
            "PRIVATE:Folder/Test.xml",
            "unknown",
            {"device_id": "x"},
        ))
        assert result.error == "Invalid device_type or device_under_test value."

    def test_desktop_device_serializes_capabilities_json(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            captured["json"] = kwargs.get("json")
            return BaseResult(result={"executionId": "exec-desktop"})

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.execute_test(
            TEST_ID,
            "desktop",
            {
                "platform_name": "Windows",
                "platform_version": "11",
                "browser_name": "Chrome",
                "browser_version": "120",
                "resolution": "1920x1080",
                "location": "US",
            },
        ))

        assert result.error is None
        dut = json.loads(captured["json"]["params"]["DUT"])
        assert dut["platformName"] == "Windows"
        assert dut["browserName"] == "Chrome"
        assert dut["resolution"] == "1920x1080"

    def test_desktop_device_sends_null_for_unspecified_capabilities(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            captured["json"] = kwargs.get("json")
            return BaseResult(result={"executionId": "exec-desktop-partial"})

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.execute_test(
            TEST_ID,
            "desktop",
            {"platform_name": "Windows"},
        ))

        assert result.error is None
        dut = json.loads(captured["json"]["params"]["DUT"])
        assert dut["platformName"] == "Windows"
        assert dut["browserName"] is None
        assert dut["location"] is None


class TestListAndReadOperations:
    def test_list_tests_returns_paginated_items(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(
                _token,
                method,
                endpoint=None,
                result_formatter=None,
                result_formatter_params=None,
                **kwargs,
        ):
            captured["endpoint"] = endpoint
            from formatters.ai_scriptless import format_ai_scriptless_tests
            formatted = format_ai_scriptless_tests(
                _tests_tree_response(),
                result_formatter_params,
            )
            return BaseResult(result=formatted)

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)
        monkeypatch.setattr(
            ai_scriptless_manager.perfecto,
            "get_ai_scriptless_api_url",
            lambda _cloud: "https://demo.app.perfectomobile.com/perfectomobile/ai-scriptless/api",
        )

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.list_tests({"page_index": 1, "visibility": "PRIVATE"}))

        assert result.error is None
        assert result.result.count == 1
        assert "PRIVATE:My Folder/Login.xml" in result.result.items[0]
        assert result.info is not None
        assert captured["endpoint"].endswith("/scripts/tree")

    def test_list_tests_propagates_api_error(self, perfecto_token, monkeypatch):
        async def fake_api_request(*_args, **_kwargs):
            return BaseResult(error="tree unavailable")

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.list_tests({}))
        assert result.error == "tree unavailable"

    def test_list_filter_values_returns_requested_filters(self, perfecto_token, monkeypatch):
        async def fake_api_request(
                _token,
                _method,
                endpoint=None,
                result_formatter=None,
                result_formatter_params=None,
                **kwargs,
        ):
            from formatters.ai_scriptless import format_ai_scriptless_tests_filter_values
            formatted = format_ai_scriptless_tests_filter_values(_tests_tree_response())
            return BaseResult(result=formatted)

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.list_filter_values(["test_name", "owner_list"]))

        assert result.error is None
        assert "Login" in result.result["test_name"]
        assert "alice" in result.result["owner_list"]

    def test_list_filter_values_rejects_unknown_filter(self, perfecto_token, monkeypatch):
        async def fake_api_request(*_args, **kwargs):
            from formatters.ai_scriptless import format_ai_scriptless_tests_filter_values
            return BaseResult(result=format_ai_scriptless_tests_filter_values(_tests_tree_response()))

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.list_filter_values(["bad_filter"]))

        assert "invalid filter_names" in result.error
        assert result.warning is not None

    def test_list_commands_appends_selection_policy(self, perfecto_token, monkeypatch):
        catalog = {
            "name": "Root",
            "children": [
                {
                    "commandId": "ai_user-action",
                    "name": "User action",
                    "path": "/ai/user-action",
                },
            ],
        }

        async def fake_api_request(
                _token,
                _method,
                endpoint=None,
                result_formatter=None,
                result_formatter_params=None,
                **kwargs,
        ):
            from formatters.ai_scriptless import format_command_catalog
            return BaseResult(result=format_command_catalog(catalog))

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.list_commands())

        assert result.error is None
        assert result.result[0].command_id == "ai_user-action"
        assert any("ai_user-action" in line for line in result.info)

    def test_list_commands_checkpoint_query_param(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            captured["endpoint"] = endpoint
            return BaseResult(result=[])

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.list_commands(checkpoint=True))

        assert result.error is None
        assert "checkpoint=true" in captured["endpoint"]

    def test_view_test_structure_formats_script(self, perfecto_token, monkeypatch):
        async def fake_api_request(
                _token,
                _method,
                endpoint=None,
                result_formatter=None,
                result_formatter_params=None,
                **kwargs,
        ):
            from formatters.ai_scriptless import format_test_structure
            return BaseResult(result=format_test_structure(
                _script_payload(),
                result_formatter_params,
            ))

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.view_test_structure(TEST_ID))

        assert result.error is None
        assert result.result.item_key == TEST_ID
        assert result.result.flow_elements[0].step_path == "0"
        assert result.info is not None

    def test_view_test_structure_requires_test_id(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.view_test_structure(""))
        assert result.error == "test_id is required (itemKey from list_tests)"

    def test_get_command_definitions_posts_ids(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            captured["json"] = kwargs.get("json")
            from formatters.ai_scriptless import format_command_definitions
            return BaseResult(result=format_command_definitions({
                "definitions": [{
                    "commandId": "wait",
                    "data": {"display": {"name": "Wait"}, "mandatoryParameters": [], "optionalParameters": []},
                }],
            }))

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.get_command_definitions(["wait"]))

        assert result.error is None
        assert captured["json"]["commandIds"] == ["wait"]
        assert result.result[0].command_id == "wait"

    def test_view_snapshot_fetches_historical_snapshot(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(
                _token,
                method,
                endpoint=None,
                result_formatter=None,
                result_formatter_params=None,
                **kwargs,
        ):
            captured["endpoint"] = endpoint
            from formatters.ai_scriptless import format_test_structure
            return BaseResult(result=format_test_structure(
                _script_payload(),
                result_formatter_params,
            ))

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.view_snapshot("PRIVATE:Folder/Test.xml@uuid-1"))

        assert result.error is None
        assert "snapshots?itemKey=" in captured["endpoint"]
        assert result.result.flow_elements[0].step_path == "0"


class TestManagerValidation:
    def test_add_command_requires_test_id(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_command("", "ai_user-action"))
        assert result.error == "test_id is required"

    def test_add_command_requires_command_id(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_command("PRIVATE:Folder/Test.xml", ""))
        assert "command_id is required" in result.error

    def test_view_snapshot_rejects_current_marker(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.view_snapshot("<current>"))
        assert "not a historical snapshot" in result.error

    def test_modify_command_requires_cmd_arguments(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.modify_command(TEST_ID, "0", {}))
        assert result.error == "cmd_arguments is required"

    def test_save_test_requires_test_id(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.save_test(""))
        assert result.error == "test_id is required"

    def test_create_test_requires_name(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.create_test(""))
        assert result.error == "name is required"

    def test_save_test_as_requires_name(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.save_test_as(TEST_ID, ""))
        assert result.error == "name is required"


class TestCommandMutations:
    def test_add_command_inserts_and_returns_step_path(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, captured=captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_command(
            TEST_ID,
            "wait",
            cmd_arguments={"duration": "3"},
        ))

        _assert_step_path_notes(result)
        assert result.result["command_id"] == "wait"
        assert result.result["step_path"] == "0"
        assert len(captured["script"]["flowElements"]) == 1
        assert captured["script"]["flowElements"][0]["command"] == "wait"

    def test_modify_command_updates_arguments(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, _script_with_steps("wait"), captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.modify_command(
            TEST_ID,
            "0",
            {"duration": "5"},
        ))

        _assert_step_path_notes(result)
        args = {
            a["name"]: a["data"]["value"]
            for a in captured["script"]["flowElements"][0]["arguments"]
        }
        assert args["duration"] == "5"

    def test_modify_command_returns_error_for_missing_step_path(self, perfecto_token, monkeypatch):
        _mock_load_and_mutate(monkeypatch, _script_with_steps("wait"))

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.modify_command(TEST_ID, "9", {"duration": "1"}))

        assert result.error == "step_path not found: 9"

    def test_delete_command_removes_step(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, _script_with_steps("wait", "comment"), captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.delete_command(TEST_ID, "0"))

        _assert_step_path_notes(result)
        assert len(captured["script"]["flowElements"]) == 1
        assert captured["script"]["flowElements"][0]["command"] == "comment"

    def test_set_command_enabled(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, _script_with_steps("wait"), captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.set_command_enabled(TEST_ID, "0", False))

        _assert_step_path_notes(result)
        assert result.result["active"] is False
        assert captured["script"]["flowElements"][0]["active"] is False

    def test_move_command_requires_target_path(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.move_command(TEST_ID, "0"))
        assert result.error == "after_path or parent_path is required"

    def test_move_command_reorders_within_root(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, _script_with_steps("wait", "comment"), captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.move_command(TEST_ID, "0", after_path="0"))

        _assert_step_path_notes(result)
        commands = [e["command"] for e in captured["script"]["flowElements"]]
        assert commands == ["comment", "wait"]

    def test_add_command_after_path(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, _script_with_steps("wait", "comment"), captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_command(
            TEST_ID,
            "ai_user-action",
            cmd_arguments={"action": "Tap"},
            after_path="0",
        ))

        _assert_step_path_notes(result)
        assert result.result["step_path"] == "1"
        assert result.result["command_id"] == "ai_user-action"
        assert len(captured["script"]["flowElements"]) == 3
        assert captured["script"]["flowElements"][1]["command"] == "ai"

    def test_add_command_inside_logical_step(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, _script_with_logical_group(), captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_command(
            TEST_ID,
            "comment",
            cmd_arguments={"text": "inside"},
            parent_path="0",
        ))

        _assert_step_path_notes(result)
        nested = captured["script"]["flowElements"][0]["flowElements"]
        assert len(nested) == 1
        assert nested[0]["command"] == "comment"
        assert result.result["step_path"] == "0.0"

    def test_add_command_propagates_load_and_mutate_error(self, perfecto_token, monkeypatch):
        async def fake_load_and_mutate(*_args, **_kwargs):
            return BaseResult(error="persist failed")

        monkeypatch.setattr(ai_scriptless_manager, "load_and_mutate", fake_load_and_mutate)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_command(TEST_ID, "wait"))
        assert result.error == "persist failed"

    def test_move_command_into_logical_step(self, perfecto_token, monkeypatch):
        captured: dict = {}
        group = build_logical_step("Setup")
        script = new_empty_script()
        script["flowElements"] = [group, build_flow_element("wait")]
        script["numOfFlowElements"] = 2
        _mock_load_and_mutate(monkeypatch, script, captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.move_command(TEST_ID, "1", parent_path="0"))

        _assert_step_path_notes(result)
        assert captured["script"]["flowElements"][0]["flowElements"][0]["command"] == "wait"
        assert len(captured["script"]["flowElements"]) == 1


class TestStructureMutations:
    def test_add_logical_step(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, captured=captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_logical_step(TEST_ID, label="Setup"))

        _assert_step_path_notes(result)
        assert result.result["structure_type"] == "LogicalStep"
        assert captured["script"]["flowElements"][0]["@type"] == "LogicalStep"

    def test_add_logical_step_inside_container(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, _script_with_logical_group(), captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_logical_step(TEST_ID, label="Nested", parent_path="0"))

        _assert_step_path_notes(result)
        nested = captured["script"]["flowElements"][0]["flowElements"]
        assert len(nested) == 1
        assert nested[0]["@type"] == "LogicalStep"
        assert result.result["step_path"] == "0.0"

    def test_add_loop_rejects_invalid_count(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_loop(TEST_ID, count=0))
        assert result.error == "count must be at least 1"

    def test_add_loop_returns_count(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, captured=captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_loop(TEST_ID, count=3))

        _assert_step_path_notes(result)
        assert result.result["count"] == 3
        assert captured["script"]["flowElements"][0]["iterator"]["count"] == 3

    def test_add_loop_inside_logical_step(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, _script_with_logical_group(), captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_loop(TEST_ID, count=2, parent_path="0"))

        _assert_step_path_notes(result)
        nested = captured["script"]["flowElements"][0]["flowElements"]
        assert len(nested) == 1
        assert nested[0]["@type"] == "Loop"
        assert nested[0]["iterator"]["count"] == 2
        assert result.result["step_path"] == "0.0"

    def test_add_condition_with_expression(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, captured=captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_condition(TEST_ID, expression="x == 1", label="Check"))

        _assert_step_path_notes(result)
        assert result.result["expression"] == "x == 1"
        assert captured["script"]["flowElements"][0]["@type"] == "IfStatement"

    def test_add_condition_inside_then_branch(self, perfecto_token, monkeypatch):
        captured: dict = {}
        script = new_empty_script()
        script["flowElements"] = [build_if_statement("x == 1", "Check")]
        _mock_load_and_mutate(monkeypatch, script, captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_condition(
            TEST_ID,
            expression="y == 2",
            label="Nested",
            parent_path="0.b0",
        ))

        _assert_step_path_notes(result)
        then_branch = captured["script"]["flowElements"][0]["branches"][0]
        assert then_branch["flowElements"][0]["@type"] == "IfStatement"
        assert result.result["step_path"] == "0.b0.0"

    def test_set_condition_expression(self, perfecto_token, monkeypatch):
        captured: dict = {}
        script = new_empty_script()
        script["flowElements"] = [build_if_statement("old", "If")]
        _mock_load_and_mutate(monkeypatch, script, captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.set_condition_expression(TEST_ID, "0", "new == true"))

        _assert_step_path_notes(result)
        assert result.result["expression"] == "new == true"
        assert captured["script"]["flowElements"][0]["expression"] == "new == true"

    def test_set_condition_expression_requires_expression(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.set_condition_expression(TEST_ID, "0", ""))
        assert result.error == "expression is required"


class TestVariableOperations:
    def test_list_test_variables(self, perfecto_token, monkeypatch):
        script = new_empty_script()
        script["variables"] = [{
            "@type": "Variable",
            "data": {
                "@type": "StringData",
                "name": "token",
                "value": "abc",
                "secured": False,
                "description": None,
                "displayName": None,
            },
        }]

        async def fake_fetch(_token, _test_id):
            return BaseResult(result={"script": script})

        monkeypatch.setattr(ai_scriptless_manager, "fetch_script_payload", fake_fetch)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.list_test_variables(TEST_ID))

        assert result.error is None
        assert len(result.result) == 1
        assert result.result[0].name == "token"

    def test_list_test_variables_propagates_fetch_error(self, perfecto_token, monkeypatch):
        async def fake_fetch(_token, _test_id):
            return BaseResult(error="script missing")

        monkeypatch.setattr(ai_scriptless_manager, "fetch_script_payload", fake_fetch)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.list_test_variables(TEST_ID))
        assert result.error == "script missing"

    def test_add_test_variable(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, captured=captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_test_variable(
            TEST_ID, "count", "number", 42, set_at_runtime=True,
        ))

        assert result.error is None
        assert result.result["name"] == "count"
        assert result.result["type"] == "number"
        assert result.result["set_at_runtime"] is True
        assert captured["script"]["variables"][0]["@type"] == "Parameter"

    def test_modify_test_variable_requires_change(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.modify_test_variable(TEST_ID, "token"))
        assert "At least one of value, variable_type, or set_at_runtime is required" in result.error

    def test_modify_test_variable(self, perfecto_token, monkeypatch):
        captured: dict = {}
        script = new_empty_script()
        script["variables"] = [{
            "@type": "Variable",
            "data": {
                "@type": "StringData",
                "name": "token",
                "value": "old",
                "secured": False,
                "description": None,
                "displayName": None,
            },
        }]
        _mock_load_and_mutate(monkeypatch, script, captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.modify_test_variable(TEST_ID, "token", value="new"))

        assert result.error is None
        assert captured["script"]["variables"][0]["data"]["value"] == "new"

    def test_delete_test_variable(self, perfecto_token, monkeypatch):
        captured: dict = {}
        script = new_empty_script()
        script["variables"] = [{
            "@type": "Variable",
            "data": {
                "@type": "StringData",
                "name": "token",
                "value": "x",
                "secured": False,
                "description": None,
                "displayName": None,
            },
        }]
        _mock_load_and_mutate(monkeypatch, script, captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.delete_test_variable(TEST_ID, "token"))

        assert result.error is None
        assert captured["script"]["variables"] == []


class TestRepositoryOperations:
    def test_create_test_persists_empty_script(self, perfecto_token, monkeypatch):
        persisted: dict = {}

        async def fake_persist(_token, item_key, script, saved_script=None, snapshot_comment=None):
            persisted["item_key"] = item_key
            persisted["flow_count"] = len(script.get("flowElements", []))
            return BaseResult(result={"draft_key": "d-1", "status": "ok"})

        monkeypatch.setattr(ai_scriptless_manager, "persist_script", fake_persist)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.create_test("Login", folder="My Folder"))

        assert result.error is None
        assert persisted["item_key"] == "PRIVATE:My Folder/Login.xml"
        assert persisted["flow_count"] == 0
        assert result.info is not None

    def test_save_test_passes_snapshot_comment(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, captured=captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.save_test(TEST_ID, comment="checkpoint"))

        assert result.error is None
        assert captured["snapshot_comment"] == "checkpoint"

    def test_save_test_as_fetches_and_persists_under_new_key(self, perfecto_token, monkeypatch):
        source_script = _script_with_steps("wait")
        persisted: dict = {}

        async def fake_fetch(_token, _test_id):
            return BaseResult(result={"script": source_script})

        async def fake_persist(_token, item_key, script, saved_script=None, snapshot_comment=None):
            persisted["item_key"] = item_key
            persisted["flow_count"] = len(script.get("flowElements", []))
            persisted["comment"] = snapshot_comment
            return BaseResult(result={"draft_key": "d-2", "status": "ok"})

        monkeypatch.setattr(ai_scriptless_manager, "fetch_script_payload", fake_fetch)
        monkeypatch.setattr(ai_scriptless_manager, "persist_script", fake_persist)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.save_test_as(
            TEST_ID,
            "Copy",
            folder="Archive",
            visibility="PUBLIC",
            comment="branched",
        ))

        assert result.error is None
        assert persisted["item_key"] == "PUBLIC:Archive/Copy.xml"
        assert persisted["flow_count"] == 1
        assert persisted["comment"] == "branched"

    def test_save_test_as_propagates_fetch_error(self, perfecto_token, monkeypatch):
        async def fake_fetch(_token, _test_id):
            return BaseResult(error="source missing")

        monkeypatch.setattr(ai_scriptless_manager, "fetch_script_payload", fake_fetch)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.save_test_as(TEST_ID, "Copy"))
        assert result.error == "source missing"

    def test_move_test_propagates_api_error(self, perfecto_token, monkeypatch):
        async def fake_api_request(*_args, **_kwargs):
            return BaseResult(error="move denied")

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.move_test(TEST_ID, "Archive"))
        assert result.error == "move denied"

    def test_list_snapshots_rejects_invalid_item_key(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.list_snapshots("invalid"))
        assert "Invalid itemKey format" in result.error

    def test_move_test_builds_target_item_key(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            captured["method"] = method
            captured["json"] = kwargs.get("json")
            return BaseResult(result={"status": "moved"})

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.move_test(TEST_ID, "Archive", visibility="PUBLIC"))

        assert result.error is None
        assert captured["method"] == "PATCH"
        assert captured["json"]["folderType"] == "PRIVATE"
        assert captured["json"]["targetFolderType"] == "PUBLIC"
        assert result.result["target_item_key"] == "PUBLIC:Archive/Test.xml"
        assert result.result["source_item_key"] == TEST_ID

    def test_move_test_rejects_invalid_item_key(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.move_test("not-an-item-key", "Archive"))
        assert "Invalid itemKey format" in result.error

    def test_delete_test_calls_repository_api(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            captured["method"] = method
            captured["params"] = kwargs.get("params")
            return BaseResult(result={"status": "deleted"})

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.delete_test(TEST_ID))

        assert result.error is None
        assert captured["method"] == "DELETE"
        assert captured["params"]["itemKey"] == TEST_ID

    def test_delete_test_propagates_api_error(self, perfecto_token, monkeypatch):
        async def fake_api_request(*_args, **_kwargs):
            return BaseResult(error="delete denied")

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.delete_test(TEST_ID))
        assert result.error == "delete denied"

    def test_list_snapshots_posts_search_body(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            captured["method"] = method
            captured["json"] = kwargs.get("json")
            return BaseResult(result=[])

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.list_snapshots(TEST_ID))

        assert result.error is None
        assert captured["method"] == "POST"
        assert captured["json"]["folderType"] == "PRIVATE"
        assert captured["json"]["keyDetails"]["artifactId"] == "Folder/Test.xml"

    def test_list_snapshots_propagates_api_error(self, perfecto_token, monkeypatch):
        async def fake_api_request(*_args, **_kwargs):
            return BaseResult(error="snapshots unavailable")

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.list_snapshots(TEST_ID))
        assert result.error == "snapshots unavailable"

    def test_get_command_definitions_requires_ids(self, perfecto_token):
        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.get_command_definitions([]))
        assert result.error == "command_ids is required and must not be empty"


def _dispatcher_action_cases() -> list[tuple[str, dict]]:
    test_id = TEST_ID
    return [
        ("list_tests", {"page_index": 1}),
        ("list_filter_values", {"filter_names": ["owner_list"]}),
        ("execute_test", {
            "test_id": test_id,
            "device_type": "real",
            "device_under_test": {"device_id": "DEV-9"},
        }),
        ("view_test_structure", {"test_id": test_id}),
        ("list_commands", {"checkpoint": True}),
        ("get_command_definitions", {"command_ids": ["wait"]}),
        ("add_command", {"test_id": test_id, "command_id": "comment", "cmd_arguments": {"text": "hi"}}),
        ("modify_command", {"test_id": test_id, "step_path": "0", "cmd_arguments": {"duration": "2"}}),
        ("delete_command", {"test_id": test_id, "step_path": "0"}),
        ("set_command_enabled", {"test_id": test_id, "step_path": "0", "enabled": False}),
        ("save_test", {"test_id": test_id, "comment": "saved"}),
        ("create_test", {"name": "New", "folder": "Folder"}),
        ("save_test_as", {"test_id": test_id, "name": "Copy", "folder": "Archive"}),
        ("add_logical_step", {"test_id": test_id, "label": "Group"}),
        ("add_loop", {"test_id": test_id, "count": 2}),
        ("add_condition", {"test_id": test_id, "expression": "true", "label": "If"}),
        ("set_condition_expression", {"test_id": test_id, "step_path": "1", "expression": "false"}),
        ("move_command", {"test_id": test_id, "step_path": "0", "after_path": "0"}),
        ("delete_test", {"test_id": test_id}),
        ("move_test", {"test_id": test_id, "folder": "Moved"}),
        ("list_snapshots", {"test_id": test_id}),
        ("view_snapshot", {"snapshot_id": f"{test_id}@hist-1"}),
        ("list_test_variables", {"test_id": test_id}),
        ("add_test_variable", {"test_id": test_id, "name": "v", "value": "1"}),
        ("modify_test_variable", {"test_id": test_id, "name": "token", "value": "new"}),
        ("delete_test_variable", {"test_id": test_id, "name": "token"}),
    ]


def _setup_dispatcher_mocks(monkeypatch, captured: dict | None = None, persisted: dict | None = None):
    script = new_empty_script()
    script["flowElements"] = [
        build_flow_element("wait"),
        build_if_statement("x == 1", "If"),
    ]
    script["numOfFlowElements"] = 2
    script["variables"] = [{
        "@type": "Variable",
        "data": {
            "@type": "StringData",
            "name": "token",
            "value": "old",
            "secured": False,
            "description": None,
            "displayName": None,
        },
    }]

    async def fake_api_request(
            _token,
            method,
            endpoint=None,
            result_formatter=None,
            result_formatter_params=None,
            **kwargs,
    ):
        if result_formatter is None:
            return BaseResult(result={"status": "ok", "executionId": "exec-1"})

        formatter_name = getattr(result_formatter, "__name__", "")
        if formatter_name == "format_ai_scriptless_tests":
            raw = _tests_tree_response()
        elif formatter_name == "format_ai_scriptless_tests_filter_values":
            raw = _tests_tree_response()
        elif formatter_name == "format_test_structure":
            raw = _script_payload()
        elif formatter_name == "format_command_catalog":
            raw = {
                "name": "Root",
                "children": [{"commandId": "wait", "name": "Wait", "path": "/wait"}],
            }
        elif formatter_name == "format_command_definitions":
            raw = {
                "definitions": [{
                    "commandId": "wait",
                    "data": {
                        "display": {"name": "Wait"},
                        "mandatoryParameters": [],
                        "optionalParameters": [],
                    },
                }],
            }
        elif formatter_name == "format_snapshots_list":
            raw = {"snapshots": [{"key": "<current>", "comment": "live"}]}
        else:
            raw = {}

        return BaseResult(result=result_formatter(raw, result_formatter_params))

    async def fake_fetch(_token, _test_id):
        return BaseResult(result={"script": copy.deepcopy(script)})

    async def fake_persist(_token, item_key, payload, saved_script=None, snapshot_comment=None):
        if persisted is not None:
            persisted["item_key"] = item_key
            persisted["comment"] = snapshot_comment
            persisted["flow_count"] = len(payload.get("flowElements", []))
        return BaseResult(result={"draft_key": "d-1", "status": "ok"})

    async def fake_load_and_mutate(_token, test_id, mutator, snapshot_comment=None):
        payload = copy.deepcopy(script)
        try:
            outcome = mutator(payload)
            if inspect.isawaitable(outcome):
                await outcome
        except ValueError as exc:
            return BaseResult(error=str(exc))
        if captured is not None:
            captured["script"] = payload
            captured["snapshot_comment"] = snapshot_comment
        return BaseResult(result={"item_key": test_id, "draft_key": "draft-1", "status": "ok"})

    monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)
    monkeypatch.setattr(ai_scriptless_manager, "fetch_script_payload", fake_fetch)
    monkeypatch.setattr(ai_scriptless_manager, "persist_script", fake_persist)
    monkeypatch.setattr(ai_scriptless_manager, "load_and_mutate", fake_load_and_mutate)


class TestAiScriptlessDispatcher:
    def test_unknown_action_returns_error(self, perfecto_token):
        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, "not_a_real_action", {}))
        assert "not found in AI Scriptless manager tool" in result.error

    def test_routes_add_command(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, captured=captured)

        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, "add_command", {
            "test_id": TEST_ID,
            "command_id": "wait",
            "cmd_arguments": {"duration": "1"},
        }))

        assert result.error is None
        assert result.result["command_id"] == "wait"
        assert len(captured["script"]["flowElements"]) == 1

    def test_routes_list_test_variables(self, perfecto_token, monkeypatch):
        script = new_empty_script()
        script["variables"] = [{
            "@type": "Variable",
            "data": {
                "@type": "StringData",
                "name": "flag",
                "value": "on",
                "secured": False,
                "description": None,
                "displayName": None,
            },
        }]

        async def fake_fetch(_token, _test_id):
            return BaseResult(result={"script": script})

        monkeypatch.setattr(ai_scriptless_manager, "fetch_script_payload", fake_fetch)

        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, "list_test_variables", {"test_id": TEST_ID}))

        assert result.error is None
        assert result.result[0].name == "flag"

    def test_defaults_none_args_to_empty_dict(self, perfecto_token, monkeypatch):
        async def fake_api_request(*_args, **_kwargs):
            return BaseResult(error="tree unavailable")

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, "list_tests", None))
        assert result.error == "tree unavailable"

    def test_routes_move_command(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, _script_with_steps("wait", "comment"), captured)

        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(
            tool, "move_command", {"test_id": TEST_ID, "step_path": "0", "after_path": "0"},
        ))

        assert result.error is None
        commands = [e["command"] for e in captured["script"]["flowElements"]]
        assert commands == ["comment", "wait"]

    def test_routes_delete_command(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _mock_load_and_mutate(monkeypatch, _script_with_steps("wait", "comment"), captured)

        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, "delete_command", {"test_id": TEST_ID, "step_path": "0"}))

        assert result.error is None
        assert len(captured["script"]["flowElements"]) == 1

    def test_routes_execute_test(self, perfecto_token, monkeypatch):
        captured: dict = {}

        async def fake_api_request(_token, method, endpoint=None, **kwargs):
            captured["json"] = kwargs.get("json")
            return BaseResult(result={"executionId": "exec-dispatch"})

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, "execute_test", {
            "test_id": TEST_ID,
            "device_type": "real",
            "device_under_test": {"device_id": "DEV-1"},
        }))

        assert result.error is None
        assert captured["json"]["params"]["DUT"] == "DEV-1"

    def test_routes_create_test(self, perfecto_token, monkeypatch):
        persisted: dict = {}

        async def fake_persist(_token, item_key, script, saved_script=None, snapshot_comment=None):
            persisted["item_key"] = item_key
            return BaseResult(result={"draft_key": "d-1", "status": "ok"})

        monkeypatch.setattr(ai_scriptless_manager, "persist_script", fake_persist)

        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, "create_test", {"name": "Smoke", "folder": "QA"}))

        assert result.error is None
        assert persisted["item_key"] == "PRIVATE:QA/Smoke.xml"

    @pytest.mark.parametrize("action,args,expected_error", [
        ("modify_command", {"test_id": TEST_ID, "step_path": "0"}, "cmd_arguments is required"),
        ("delete_test", {"test_id": ""}, "test_id is required"),
        ("move_test", {"test_id": "", "folder": "Archive"}, "test_id is required"),
    ])
    def test_dispatcher_validation_errors(self, perfecto_token, action, args, expected_error):
        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, action, args))
        if expected_error:
            assert expected_error in result.error

    def test_http_status_error_returns_formatted_error(self, perfecto_token, monkeypatch):
        async def raise_http_error(*_args, **_kwargs):
            request = httpx.Request("GET", "https://demo.perfectomobile.com/tree")
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError("service unavailable", request=request, response=response)

        monkeypatch.setattr(ai_scriptless_manager, "api_request", raise_http_error)

        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, "list_tests", {}))

        assert result.error is not None
        assert result.error.startswith("Error:")
        assert "HTTPStatusError" in result.error

    def test_unexpected_exception_includes_support_message(self, perfecto_token, monkeypatch):
        async def raise_runtime_error(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(ai_scriptless_manager, "api_request", raise_runtime_error)

        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, "list_tests", {}))

        assert "boom" in result.error
        assert SUPPORT_MESSAGE in result.error

    def test_view_test_structure_end_to_end_with_formatter(self, perfecto_token, monkeypatch):
        """api_request mock returns raw payload; formatter runs inside manager call chain."""
        async def fake_api_request(
                _token,
                _method,
                endpoint=None,
                result_formatter=None,
                result_formatter_params=None,
                **kwargs,
        ):
            from formatters.ai_scriptless import format_test_structure
            return BaseResult(result=format_test_structure(
                _script_payload(),
                result_formatter_params,
            ))

        monkeypatch.setattr(ai_scriptless_manager, "api_request", fake_api_request)

        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, "view_test_structure", {"test_id": TEST_ID}))

        assert result.error is None
        assert result.result.item_key == TEST_ID
        assert result.result.flow_elements[0].step_path == "0"
        assert any("AI Scriptless UI" in line for line in result.info)

    def test_routes_list_filter_values(self, perfecto_token, monkeypatch):
        _setup_dispatcher_mocks(monkeypatch)

        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, "list_filter_values", {"filter_names": ["test_name", "owner_list"]}))

        assert result.error is None
        assert "Login" in result.result["test_name"]

    def test_routes_save_test_as(self, perfecto_token, monkeypatch):
        persisted: dict = {}
        _setup_dispatcher_mocks(monkeypatch, persisted=persisted)

        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, "save_test_as", {
            "test_id": TEST_ID,
            "name": "Branch",
            "folder": "Copies",
            "visibility": "PUBLIC",
            "comment": "v2",
        }))

        assert result.error is None
        assert persisted["item_key"] == "PUBLIC:Copies/Branch.xml"
        assert persisted["comment"] == "v2"

    def test_routes_add_test_variable(self, perfecto_token, monkeypatch):
        captured: dict = {}
        _setup_dispatcher_mocks(monkeypatch, captured=captured)

        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, "add_test_variable", {
            "test_id": TEST_ID,
            "name": "retry",
            "variable_type": "number",
            "value": 3,
            "set_at_runtime": True,
        }))

        assert result.error is None
        assert result.result["name"] == "retry"
        names = [v["data"]["name"] for v in captured["script"]["variables"]]
        assert "retry" in names

    @pytest.mark.parametrize("action,args", _dispatcher_action_cases())
    def test_dispatcher_routes_registered_action(self, perfecto_token, monkeypatch, action, args):
        _setup_dispatcher_mocks(monkeypatch)

        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, action, args))

        assert "not found in AI Scriptless manager tool" not in (result.error or "")


def _call_tool(tool, action, args, ctx=None):
    return tool(arguments={"action": action, "args": args}, ctx=ctx)


def _register_tool(token):
    class _McpStub:
        def __init__(self):
            self.tools: dict = {}

        def tool(self, *, name, description):
            def decorator(fn):
                self.tools[name] = fn
                return fn
            return decorator

    mcp = _McpStub()
    ai_scriptless_manager.register(mcp, token)
    return mcp.tools["perfecto_ai_scriptless"]


class TestCmdArgumentsValidation:
    def test_add_command_rejects_undeclared_argument_name(
            self, perfecto_token, monkeypatch, declare_command_parameters):
        declare_command_parameters({"ai_user-action": (["action"], ["handsetId"])})
        _mock_load_and_mutate(monkeypatch)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_command(
            TEST_ID,
            "ai_user-action",
            cmd_arguments={"actions": "Tap on Login"},
        ))

        assert "Unknown cmd_arguments for command 'ai_user-action'" in result.error
        assert "did you mean 'action'" in result.error
        assert "get_command_definitions" in result.error

    def test_add_command_accepts_declared_argument_name(
            self, perfecto_token, monkeypatch, declare_command_parameters):
        captured: dict = {}
        declare_command_parameters({"ai_user-action": (["action"], ["handsetId"])})
        _mock_load_and_mutate(monkeypatch, captured=captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_command(
            TEST_ID,
            "ai_user-action",
            cmd_arguments={"action": "Tap on Login"},
        ))

        assert result.error is None
        arguments = captured["script"]["flowElements"][0]["arguments"]
        assert {argument["name"] for argument in arguments} == {"action", "handsetId"}

    def test_add_command_accepts_canonical_name_when_alias_is_declared(
            self, perfecto_token, monkeypatch, declare_command_parameters):
        # The repository declares waitDuration; the spec canonicalizes it to duration.
        declare_command_parameters({"wait": (["waitDuration"], [])})
        _mock_load_and_mutate(monkeypatch)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_command(TEST_ID, "wait", cmd_arguments={"duration": "3"}))

        assert result.error is None

    def test_add_command_fails_open_without_definitions(self, perfecto_token, monkeypatch):
        _mock_load_and_mutate(monkeypatch)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_command(
            TEST_ID,
            "ai_user-action",
            cmd_arguments={"whatever": "value"},
        ))

        assert result.error is None

    def test_add_command_notes_empty_mandatory_parameter(
            self, perfecto_token, monkeypatch, declare_command_parameters):
        declare_command_parameters({"ai_user-action": (["action"], ["handsetId"])})
        _mock_load_and_mutate(monkeypatch)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.add_command(TEST_ID, "ai_user-action"))

        assert result.error is None
        assert any("Mandatory parameter(s) left empty" in note for note in result.result["notes"])

    def test_modify_command_rejects_undeclared_argument_name(
            self, perfecto_token, monkeypatch, declare_command_parameters):
        declare_command_parameters({"wait": ([], ["duration"])})
        _mock_load_and_mutate(monkeypatch, _script_with_steps("wait"))

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.modify_command(TEST_ID, "0", {"timeout": "5"}))

        assert "Unknown cmd_arguments for command 'wait'" in result.error

    def test_modify_command_accepts_declared_argument_name(
            self, perfecto_token, monkeypatch, declare_command_parameters):
        captured: dict = {}
        declare_command_parameters({"wait": ([], ["duration"])})
        _mock_load_and_mutate(monkeypatch, _script_with_steps("wait"), captured)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        result = asyncio.run(manager.modify_command(TEST_ID, "0", {"duration": "5"}))

        assert result.error is None
        arguments = captured["script"]["flowElements"][0]["arguments"]
        assert {"name": "duration", "value": "5"} in [
            {"name": argument["name"], "value": argument["data"]["value"]} for argument in arguments
        ]

    def test_definitions_are_fetched_once_per_command(self, perfecto_token, monkeypatch):
        calls: list[str] = []

        async def counting_fetch(_token, command_id):
            calls.append(command_id)
            return frozenset({"action"}), frozenset({"handsetId"})

        definitions.reset_declared_parameters_cache()
        monkeypatch.setattr(definitions, "_fetch_declared_parameters", counting_fetch)
        _mock_load_and_mutate(monkeypatch)

        manager = AiScriptlessManager(perfecto_token, ctx=None)
        for _ in range(3):
            asyncio.run(manager.add_command(
                TEST_ID,
                "ai_user-action",
                cmd_arguments={"action": "Tap"},
            ))

        assert calls == ["ai_user-action"]

    def test_unknown_action_hints_cmd_arguments_collision(self, perfecto_token):
        tool = _register_tool(perfecto_token)
        result = asyncio.run(_call_tool(tool, "Tap on the Login button", {
            "test_id": TEST_ID,
            "command_id": "ai_user-action",
        }))

        assert "not found in AI Scriptless manager tool" in result.error
        assert "must stay nested inside 'cmd_arguments'" in result.error
