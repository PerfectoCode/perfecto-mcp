import json
import traceback
from typing import Optional, Any, Dict
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import Context
from pydantic import Field

from config import perfecto
from config.perfecto import TOOLS_PREFIX, SUPPORT_MESSAGE
from config.token import PerfectoToken, token_verify
from formatters.ai_scriptless import format_ai_scriptless_tests, \
    format_ai_scriptless_tests_filter_values, format_command_catalog, \
    format_command_definitions, format_snapshots_list, format_test_structure, \
    format_test_variables
from models.manager import Manager
from models.result import BaseResult, PaginationResult
from tools.ai_scriptless_script import (
    add_script_variable,
    build_flow_element,
    build_if_statement,
    build_item_key,
    build_logical_step,
    build_loop,
    build_move_test_body,
    build_snapshot_search_body,
    delete_script_variable,
    delete_element_by_path,
    fetch_current_username,
    fetch_script_payload,
    find_element_by_path,
    find_step_path_for_element,
    insert_flow_element,
    load_and_mutate,
    modify_script_variable,
    move_element_by_path,
    new_empty_script,
    persist_script,
    script_write_lock,
    set_condition_expression,
    set_element_enabled,
    split_item_key,
    test_file_name,
    update_element_arguments,
)
from tools.utils import api_request

STEP_PATH_REFRESH_NOTES = [
    "step_path values are dot-separated positional paths (e.g. 0, 2.0, 5.b0.1); Perfecto does not persist them.",
    "After this operation, step paths may have changed. Call view_test_structure before the next edit; "
    "do not reuse step_path values from this response.",
]


def _append_step_path_refresh_notes(result: BaseResult) -> BaseResult:
    if result.error or not isinstance(result.result, dict):
        return result
    notes = result.result.setdefault("notes", [])
    for note in STEP_PATH_REFRESH_NOTES:
        if note not in notes:
            notes.append(note)
    return result


class AiScriptlessManager(Manager):
    def __init__(self, token: Optional[PerfectoToken], ctx: Context):
        super().__init__(token, ctx)

    @token_verify
    async def list_tests(self, args: dict[str, Any]) -> BaseResult:
        page_size = 50
        page_index = args.get("page_index", 1)
        skip = (page_size * page_index) - page_size

        tree_url = perfecto.get_ai_scriptless_api_url(self.token.cloud_name)
        tree_url = tree_url + "/scripts/tree"
        tests_result = await api_request(self.token, "GET", endpoint=tree_url,
                                         result_formatter=format_ai_scriptless_tests,
                                         result_formatter_params={"page_size": page_size, "skip": skip,
                                                                  "filters": args})

        page_result = PaginationResult(
            items=tests_result.result,
            count=len(tests_result.result),
            page=page_index,
            offset=skip,
            next_offset=skip + page_size,
            has_more=page_size - len(tests_result.result) <= 0,
        )

        return BaseResult(
            result=page_result,
            error=tests_result.error,
            warning=tests_result.warning,
            info=tests_result.info,
        )

    @token_verify
    async def list_filter_values(self, filter_names: list[str]) -> BaseResult:
        tree_url = perfecto.get_ai_scriptless_api_url(self.token.cloud_name)
        tree_url = tree_url + "/scripts/tree"
        filter_values_result = await api_request(self.token, "GET", endpoint=tree_url,
                                                 result_formatter=format_ai_scriptless_tests_filter_values)
        filter_values = {}
        filter_not_found = []
        for filter_name in filter_names:
            if filter_name in filter_values_result.result:
                filter_values[filter_name] = filter_values_result.result[filter_name]
            else:
                filter_not_found.append(filter_name)

        error = None
        warnings = None
        if len(filter_not_found) > 0:
            error = f"Error, invalid filter_names values: {','.join(filter_not_found)}"
            warnings = [f"Make sure to use valid filter_names values: {','.join(['test_name', 'owner_list'])}"]

        return BaseResult(
            result=filter_values,
            error=error,
            warning=warnings,
        )

    @token_verify
    async def execute_test(self, test_id: str, device_type: str, device_under_test: dict[str, Any]) -> BaseResult:
        execute_url = perfecto.get_ai_scriptless_execution_api_url(self.token.cloud_name)

        # This mapping allows us to detect when the AI gets confused and uses Perfecto-style capabilities.
        # It also allows for reverse mapping from internal to capabilities from Perfecto.
        att_map = {
            "real": {
                "device_id": "deviceId"
            },
            "virtual": {
                "platform_name": "platformName",
                "manufacturer": "manufacturer",
                "model": "model",
                "platform_version": "platformVersion"
            },
            "desktop": {
                "platform_name": "platformName",
                "platform_version": "platformVersion",
                "browser_name": "browserName",
                "browser_version": "browserVersion",
                "resolution": "resolution",
                "location": "location"
            }
        }

        dut = None
        remapped_device_under_test = {}
        # Remap the attributes to Perfecto Capabilities format
        if device_type in att_map.keys():
            for key in att_map[device_type].keys():
                alt_key = att_map[device_type][key]
                remapped_device_under_test[alt_key] = device_under_test.get(key, device_under_test.get(alt_key, None))

        if device_type == "real":
            dut = remapped_device_under_test.get("deviceId", None)
            if dut is None:
                return BaseResult(
                    error="Invalid value for device_under_test. The key device_id could not be found."
                )
        elif device_type in ["virtual", "desktop"]:
            # Verify if all the needed keys exist on the remapped version
            key_not_found = []
            for key in att_map[device_type].keys():
                alt_key = att_map[device_type][key]
                if alt_key not in remapped_device_under_test:
                    key_not_found.append(key)
            if len(key_not_found) == 0:
                dut = json.dumps(remapped_device_under_test, separators=(',', ':'))
            else:
                keys_not_found_str = ",".join(key_not_found)
                return BaseResult(
                    error=f"Invalid value for device_under_test. The keys [{keys_not_found_str}] could not be found."
                )
        if dut is not None and len(dut) > 0:
            body = {
                "params": {
                    "DUT": dut
                },
                "testKey": test_id,
                "triggerType": "Manual"
            }
            return await api_request(self.token, "POST", endpoint=execute_url, json=body)
        else:
            return BaseResult(
                error="Invalid device_type or device_under_test value."
            )

    @token_verify
    async def list_commands(self, checkpoint: bool = False) -> BaseResult:
        commands_url = perfecto.get_ai_scriptless_command_repository_url(self.token.cloud_name)
        commands_url = commands_url + "/commands"
        if checkpoint:
            commands_url = commands_url + "?checkpoint=true"
        return await api_request(self.token, "GET", endpoint=commands_url,
                                 result_formatter=format_command_catalog)

    @token_verify
    async def get_command_definitions(self, command_ids: list[str]) -> BaseResult:
        if not command_ids:
            return BaseResult(error="command_ids is required and must not be empty")
        definitions_url = perfecto.get_ai_scriptless_command_repository_url(self.token.cloud_name)
        definitions_url = definitions_url + "/commands/definitions"
        return await api_request(self.token, "POST", endpoint=definitions_url,
                                 json={"commandIds": command_ids},
                                 result_formatter=format_command_definitions)

    @token_verify
    async def view_test_structure(self, test_id: str) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required (itemKey from list_tests)")
        script_url = perfecto.get_ai_scriptless_api_url(self.token.cloud_name)
        script_url = script_url + f"/script?itemKey={quote(test_id, safe='')}"
        return await api_request(self.token, "GET", endpoint=script_url,
                                 result_formatter=format_test_structure,
                                 result_formatter_params={"item_key": test_id})

    @token_verify
    async def add_command(
            self,
            test_id: str,
            command_id: str,
            arguments: Optional[dict[str, Any]] = None,
            after_path: Optional[str] = None,
            parent_path: Optional[str] = None,
    ) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if not command_id:
            return BaseResult(error="command_id is required (from list_commands)")

        element = build_flow_element(command_id, arguments)
        inserted_path: dict[str, Optional[str]] = {"step_path": None}

        def mutator(script: dict[str, Any]) -> None:
            insert_flow_element(script, element, after_path=after_path, parent_path=parent_path)
            inserted_path["step_path"] = find_step_path_for_element(script, element)

        result = await load_and_mutate(self.token, test_id, mutator)
        if result.error:
            return result
        result.result["step_path"] = inserted_path["step_path"]
        result.result["command_id"] = command_id
        return _append_step_path_refresh_notes(result)

    @token_verify
    async def modify_command(self, test_id: str, step_path: str, arguments: dict[str, Any]) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if not step_path:
            return BaseResult(error="step_path is required (from view_test_structure)")
        if not arguments:
            return BaseResult(error="arguments is required")

        def mutator(script: dict[str, Any]) -> None:
            located = find_element_by_path(script, step_path)
            if located is None:
                raise ValueError(f"step_path not found: {step_path}")
            _, _, element = located
            update_element_arguments(element, arguments)

        return _append_step_path_refresh_notes(
            await load_and_mutate(self.token, test_id, mutator)
        )

    @token_verify
    async def delete_command(self, test_id: str, step_path: str) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if not step_path:
            return BaseResult(error="step_path is required (from view_test_structure)")

        def mutator(script: dict[str, Any]) -> None:
            delete_element_by_path(script, step_path)

        return _append_step_path_refresh_notes(
            await load_and_mutate(self.token, test_id, mutator)
        )

    @token_verify
    async def set_command_enabled(self, test_id: str, step_path: str, enabled: bool) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if not step_path:
            return BaseResult(error="step_path is required (from view_test_structure)")

        def mutator(script: dict[str, Any]) -> None:
            set_element_enabled(script, step_path, enabled)

        result = await load_and_mutate(self.token, test_id, mutator)
        if result.error:
            return result
        result.result["step_path"] = step_path
        result.result["active"] = enabled
        return _append_step_path_refresh_notes(result)

    @token_verify
    async def save_test(self, test_id: str, comment: Optional[str] = None) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")

        def mutator(_script: dict[str, Any]) -> None:
            pass

        return await load_and_mutate(
            self.token,
            test_id,
            mutator,
            snapshot_comment=comment,
        )

    @token_verify
    async def create_test(self, name: str, folder: str = "My Folder", visibility: str = "PRIVATE") -> BaseResult:
        if not name:
            return BaseResult(error="name is required")
        item_key = build_item_key(visibility, folder, name)
        script = new_empty_script()
        return await persist_script(self.token, item_key, script)

    @token_verify
    async def save_test_as(
            self,
            test_id: str,
            name: str,
            folder: str = "My Folder",
            visibility: str = "PRIVATE",
            comment: Optional[str] = None,
    ) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if not name:
            return BaseResult(error="name is required")
        async with script_write_lock(test_id):
            payload_result = await fetch_script_payload(self.token, test_id)
            if payload_result.error:
                return payload_result
            script = payload_result.result.get("script", {})
        item_key = build_item_key(visibility, folder, name)
        return _append_step_path_refresh_notes(
            await persist_script(self.token, item_key, script, snapshot_comment=comment)
        )

    async def _add_structure(
            self,
            test_id: str,
            element: dict[str, Any],
            structure_type: str,
            after_path: Optional[str] = None,
            parent_path: Optional[str] = None,
    ) -> BaseResult:
        inserted_path: dict[str, Optional[str]] = {"step_path": None}

        def mutator(script: dict[str, Any]) -> None:
            insert_flow_element(script, element, after_path=after_path, parent_path=parent_path)
            inserted_path["step_path"] = find_step_path_for_element(script, element)

        result = await load_and_mutate(self.token, test_id, mutator)
        if result.error:
            return result
        result.result["step_path"] = inserted_path["step_path"]
        result.result["structure_type"] = structure_type
        return _append_step_path_refresh_notes(result)

    @token_verify
    async def add_logical_step(
            self,
            test_id: str,
            label: Optional[str] = None,
            after_path: Optional[str] = None,
            parent_path: Optional[str] = None,
    ) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        element = build_logical_step(label)
        return await self._add_structure(test_id, element, "LogicalStep", after_path, parent_path)

    @token_verify
    async def add_loop(
            self,
            test_id: str,
            count: int = 1,
            after_path: Optional[str] = None,
            parent_path: Optional[str] = None,
    ) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if count < 1:
            return BaseResult(error="count must be at least 1")
        element = build_loop(count)
        result = await self._add_structure(test_id, element, "Loop", after_path, parent_path)
        if not result.error:
            result.result["count"] = count
        return result

    @token_verify
    async def add_condition(
            self,
            test_id: str,
            expression: Optional[str] = None,
            label: Optional[str] = None,
            after_path: Optional[str] = None,
            parent_path: Optional[str] = None,
    ) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        element = build_if_statement(expression, label)
        result = await self._add_structure(test_id, element, "IfStatement", after_path, parent_path)
        if not result.error and expression:
            result.result["expression"] = expression
        return result

    @token_verify
    async def set_condition_expression(self, test_id: str, step_path: str, expression: str) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if not step_path:
            return BaseResult(error="step_path is required (IfStatement path from view_test_structure)")
        if not expression:
            return BaseResult(error="expression is required")

        def mutator(script: dict[str, Any]) -> None:
            set_condition_expression(script, step_path, expression)

        result = await load_and_mutate(self.token, test_id, mutator)
        if result.error:
            return result
        result.result["step_path"] = step_path
        result.result["expression"] = expression
        return _append_step_path_refresh_notes(result)

    @token_verify
    async def move_command(
            self,
            test_id: str,
            step_path: str,
            after_path: Optional[str] = None,
            parent_path: Optional[str] = None,
    ) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if not step_path:
            return BaseResult(error="step_path is required")
        if not after_path and not parent_path:
            return BaseResult(error="after_path or parent_path is required")

        def mutator(script: dict[str, Any]) -> None:
            move_element_by_path(script, step_path, after_path=after_path, parent_path=parent_path)

        result = await load_and_mutate(self.token, test_id, mutator)
        if result.error:
            return result
        result.result["step_path"] = step_path
        return _append_step_path_refresh_notes(result)

    @token_verify
    async def delete_test(self, test_id: str) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required (itemKey from list_tests)")
        delete_url = perfecto.get_ai_scriptless_api_url(self.token.cloud_name) + "/repositories"
        return await api_request(
            self.token,
            "DELETE",
            endpoint=delete_url,
            params={"itemKey": test_id},
        )

    @token_verify
    async def move_test(
            self,
            test_id: str,
            folder: str,
            visibility: Optional[str] = None,
    ) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required (itemKey from list_tests)")

        try:
            source_visibility, _ = split_item_key(test_id)
        except ValueError as exc:
            return BaseResult(error=str(exc))

        target_visibility = visibility or source_visibility
        owner = await fetch_current_username(self.token) or ""
        move_url = perfecto.get_repository_management_api_url(self.token.cloud_name) + "/directory"
        body = build_move_test_body(test_id, folder, target_visibility, owner)
        result = await api_request(self.token, "PATCH", endpoint=move_url, json=body)
        if result.error:
            return result
        target_item_key = build_item_key(
            target_visibility,
            folder,
            test_file_name(test_id).removesuffix(".xml"),
        )
        result.result = {
            "source_item_key": test_id,
            "target_item_key": target_item_key,
            "folder": folder,
            "visibility": target_visibility,
        }
        return result

    @token_verify
    async def list_snapshots(self, test_id: str) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required (itemKey from list_tests)")
        try:
            body = build_snapshot_search_body(test_id)
        except ValueError as exc:
            return BaseResult(error=str(exc))
        snapshots_url = (
            perfecto.get_repository_management_api_url(self.token.cloud_name) + "/snapshots/search"
        )
        return await api_request(
            self.token,
            "POST",
            endpoint=snapshots_url,
            json=body,
            result_formatter=format_snapshots_list,
            result_formatter_params={"test_id": test_id},
        )

    @token_verify
    async def view_snapshot(self, snapshot_id: str) -> BaseResult:
        if not snapshot_id:
            return BaseResult(error="snapshot_id is required (key from list_snapshots)")
        if snapshot_id == "<current>":
            return BaseResult(
                error="snapshot_id '<current>' is the live script marker, not a historical snapshot. "
                      "Use view_test_structure with test_id for the current editable script."
            )
        return await api_request(
            self.token,
            "GET",
            endpoint=perfecto.get_ai_scriptless_api_url(self.token.cloud_name)
            + f"/snapshots?itemKey={quote(snapshot_id, safe='')}",
            result_formatter=format_test_structure,
            result_formatter_params={"item_key": snapshot_id},
        )

    @token_verify
    async def list_test_variables(self, test_id: str) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required (itemKey from list_tests)")
        payload_result = await fetch_script_payload(self.token, test_id)
        if payload_result.error:
            return payload_result
        script = payload_result.result.get("script", {})
        variables = format_test_variables(script.get("variables", []))
        return BaseResult(result=variables)

    @token_verify
    async def add_test_variable(
            self,
            test_id: str,
            name: str,
            variable_type: str = "string",
            value: Any = "",
            set_at_runtime: bool = False,
    ) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if not name:
            return BaseResult(error="name is required")

        def mutator(script: dict[str, Any]) -> None:
            add_script_variable(script, name, variable_type, value, set_at_runtime)

        result = await load_and_mutate(self.token, test_id, mutator)
        if result.error:
            return result
        result.result["name"] = name
        result.result["type"] = variable_type
        result.result["set_at_runtime"] = set_at_runtime
        return result

    @token_verify
    async def modify_test_variable(
            self,
            test_id: str,
            name: str,
            value: Optional[Any] = None,
            variable_type: Optional[str] = None,
            set_at_runtime: Optional[bool] = None,
    ) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if not name:
            return BaseResult(error="name is required")
        if value is None and variable_type is None and set_at_runtime is None:
            return BaseResult(error="At least one of value, variable_type, or set_at_runtime is required")

        def mutator(script: dict[str, Any]) -> None:
            modify_script_variable(script, name, value, variable_type, set_at_runtime)

        result = await load_and_mutate(self.token, test_id, mutator)
        if result.error:
            return result
        result.result["name"] = name
        return result

    @token_verify
    async def delete_test_variable(self, test_id: str, name: str) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if not name:
            return BaseResult(error="name is required")

        def mutator(script: dict[str, Any]) -> None:
            delete_script_variable(script, name)

        result = await load_and_mutate(self.token, test_id, mutator)
        if result.error:
            return result
        result.result["name"] = name
        return result


def register(mcp, token: Optional[PerfectoToken]):
    @mcp.tool(
        name=f"{TOOLS_PREFIX}_ai_scriptless",
        description="""
Operations on AI Scriptless information.
Actions:
- list_tests: List all available AI Scriptless Test from Perfecto.
    args(dict): Dictionary with the following optional filter parameters:
        test_name (str): The test name to filter.
        visibility (str, default='PRIVATE' values=['PUBLIC', 'PRIVATE']): The visibility, PUBLIC=All Public Tests, PRIVATE=My private tests.
        owner_list (list[str], values= use first list_filter_values tool with 'owner_list'): The list of users to filter tests (owners).
        page_index (int, default=1), The current page number. If the result mention has_next_page in true, asks the user if they want to see the next page.
- list_filter_values: List the values needed for list_tests filters.
    args(dict): Dictionary with the following required filter parameters:
        filter_names (list[str], values=['test_name', 'owner_list']): The filter name list.
- execute_test: Execute a preconfigured AI Scriptless Test.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test ID from list_tests
        device_type (str, default='real', values=['real', 'virtual', 'desktop']: The device type. 
        device_under_test (dict, required): Device configuration object.
            When device_type='real': {device_id: str} (Get from list_real_devices).
            When device_type='virtual': {platform_name: str, manufacturer: str, model: str, platform_version: str} (Get from list_virtual_devices).
            When device_type='desktop': {platform_name: str, platform_version: str, browser_name: str, 
                          browser_version: str, resolution: str, location: str} (Get from list_desktop_devices).
- view_test_structure: View the hierarchical structure of an AI Scriptless test. Each step has step_path (dot-separated positional path, e.g. 0, 2.0, 5.b0.1).
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests (e.g. PRIVATE:My Folder/My Test.xml).
- list_commands: List available AI Scriptless commands from the command repository.
    args(dict): Dictionary with the following optional parameters:
        checkpoint (bool, default=false): If true, list checkpoint commands only.
- get_command_definitions: Get parameter definitions for one or more commands.
    args(dict): Dictionary with the following required parameters:
        command_ids (list[str]): Command IDs from list_commands (e.g. ai_user-action, checkpoint_text).
- add_command: Add a command to a test and persist it.
    args(dict): Dictionary with the following parameters:
        test_id (str, required): Test itemKey from list_tests.
        command_id (str, required): Command ID from list_commands.
        arguments (dict, optional): Command argument names to values.
        after_path (str, optional): Insert after this step (step_path from view_test_structure).
        parent_path (str, optional): Insert inside a container (step_path of LogicalStep, Loop, or Branch).
- modify_command: Update command arguments and persist.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        step_path (str): Step path from view_test_structure (e.g. 0, 2.0, 5.b0.1).
        arguments (dict): Argument names to new values.
- delete_command: Remove a command from a test and persist.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        step_path (str): Step path from view_test_structure.
- set_command_enabled: Enable or disable (exclude/include) a command and persist.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        step_path (str): Step path from view_test_structure.
        enabled (bool): True to include, false to exclude.
- save_test: Persist the current test script.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        comment (str, optional): Labels the current version on '<current>' in list_snapshots (UI: Save with comment). Every save also adds a UUID history entry.
- create_test: Create a new empty test with a DUT parameter.
    args(dict): Dictionary with the following required parameters:
        name (str): Test name without .xml extension.
        folder (str, default='My Folder'): Target folder.
        visibility (str, default='PRIVATE', values=['PUBLIC', 'PRIVATE']): Test visibility.
- save_test_as: Copy a test to a new itemKey and persist.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Source test itemKey from list_tests.
        name (str): New test name without .xml extension.
        folder (str, default='My Folder'): Target folder.
        visibility (str, default='PRIVATE', values=['PUBLIC', 'PRIVATE']): Test visibility.
        comment (str, optional): Labels the current version on '<current>' in list_snapshots for the saved copy.
- add_logical_step: Add a LogicalStep group container and persist.
    args(dict): Dictionary with the following parameters:
        test_id (str, required): Test itemKey from list_tests.
        label (str, optional): Group label.
        after_path (str, optional): Insert after this step path.
        parent_path (str, optional): Insert inside a container step path.
- add_loop: Add a Loop container and persist.
    args(dict): Dictionary with the following parameters:
        test_id (str, required): Test itemKey from list_tests.
        count (int, default=1): RepeatIterator count.
        after_path (str, optional): Insert after this step path.
        parent_path (str, optional): Insert inside a container step path.
- add_condition: Add an IfStatement condition with Then/Else branches and persist.
    args(dict): Dictionary with the following parameters:
        test_id (str, required): Test itemKey from list_tests.
        expression (str, optional): Condition expression.
        label (str, optional): Condition label.
        after_path (str, optional): Insert after this step path.
        parent_path (str, optional): Insert inside a container step path.
- set_condition_expression: Set the expression on an IfStatement and persist.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        step_path (str): IfStatement path from view_test_structure (e.g. 5).
        expression (str): Condition expression.
- move_command: Move a step to a new position and persist.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        step_path (str): Step path to move.
        after_path (str, optional): Insert after this sibling step path.
        parent_path (str, optional): Move into this container step path (LogicalStep, Loop, or Branch).
- delete_test: Delete an AI Scriptless test from the repository.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
- move_test: Move a test to another folder (same or different visibility).
    args(dict): Dictionary with the following required parameters:
        test_id (str): Source test itemKey from list_tests.
        folder (str): Target folder path without visibility prefix (e.g. 'My Folder' or 'Shared/Team').
        visibility (str, optional): Target visibility; defaults to the source test visibility.
- list_snapshots: List snapshot history for a test (includes '<current>' marker plus UUID historical versions).
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
    Returns notes explaining that every save adds history entries and how '<current>' vs UUID keys work.
- view_snapshot: View the hierarchical structure of a historical snapshot (same format as view_test_structure).
    args(dict): Dictionary with the following required parameters:
        snapshot_id (str): UUID key from list_snapshots (not '<current>'; use view_test_structure for the live script).
- list_test_variables: List script variables configured on a test (distinct from DUT parameters).
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
- add_test_variable: Add a script variable and persist.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        name (str): Variable name (letters, numbers, underscore; cannot start with a number).
        variable_type (str, default='string', values=['string', 'secured_string', 'number', 'boolean']): Variable type.
        value (any, default=''): Variable value.
        set_at_runtime (bool, default=false): When true, value is supplied at execution time.
- modify_test_variable: Update a script variable and persist.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        name (str): Existing variable name.
        value (any, optional): New value.
        variable_type (str, optional): New type (string, secured_string, number, boolean).
        set_at_runtime (bool, optional): Toggle runtime parameter behavior.
- delete_test_variable: Remove a script variable and persist.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        name (str): Variable name to delete.
Hints:
- step_path is a dot-separated positional path without spaces (0-based indices; b0=Then branch, b1=Else). Example: root step 3 is "3"; first step inside Then of condition at 5 is "5.b0.0". Perfecto does not persist paths; they change when steps are inserted, moved, or deleted. Always call view_test_structure before the next structure edit; do not reuse step_path from a previous mutation response.
- Use list_commands and get_command_definitions before add_command to discover valid command_ids and argument names.
- Use parent_path on add_command with the step_path of a LogicalStep, Loop, or Branch from view_test_structure.
- Use add_logical_step, add_loop, and add_condition to build control-flow structures matching the UI toolbar Group, Loop, and Condition actions.
- Script variables (list_test_variables, add/modify/delete_test_variable) are stored in script.variables[] and are distinct from the DUT parameter in script.parameters[].
- Snapshot behavior: every save creates a UUID history entry; comment on save_test labels '<current>'. See list_snapshots notes for details.
- Edits persist immediately via the internal draft→script pipeline (each persist also adds snapshot history; save_test is available to re-persist unchanged content).
- IMPORTANT: Always call list_filter_values first to get valid filter values before using any filters in list_tests. 
  This ensures you're using the correct test name, list of owners users or other filter values that actually exist in the system.
- If in any result has_next_page is true, ask the user if they want to see the next page or access all pages before making a subsequent call.
- Before executing a test, follow this validation workflow:
  1. list_tests (get and validate test_id).
  2. Get device configuration based on device_type:
     - 'real': list_real_devices (get device_id).
     - 'virtual': list_virtual_devices (get platform_name, manufacturer, model, platform_version).
     - 'desktop': list_desktop_devices (get platform_name, platform_version, browser_name, browser_version, resolution, location).
  3. On real device use read_real_device_info (verify device is available and not in use).
  4. execute_test (execute the test).
  5. list_report_executions with report name equal to test name and list_live_executions when the device it's in use (monitor execution progress).
- Always check before running a test_id if the device_type and device_under_test exist and is available (when it's a real device), not use device in use or malfunctioning.
- Always monitor a real device's operation while it's in use by checking the information with read_real_device_info.
- Always stop the execution by stopping the live execution (make sure it's the correct execution, such as the execution name or user ID).
"""
    )
    async def ai_scriptless(
            action: str = Field(description="The action id to execute"),
            args: Dict[str, Any] = Field(description="Dictionary with parameters", default=None),
            ctx: Context = Field(description="Context object providing access to MCP capabilities")
    ) -> BaseResult:
        if args is None:
            args = {}
        ai_scriptless_manager = AiScriptlessManager(token, ctx)
        try:
            match action:
                case "list_tests":
                    return await ai_scriptless_manager.list_tests(args)
                case "list_filter_values":
                    return await ai_scriptless_manager.list_filter_values(args.get("filter_names", []))
                case "execute_test":
                    return await ai_scriptless_manager.execute_test(args.get("test_id", ""),
                                                                    args.get("device_type", ""),
                                                                    args.get("device_under_test", {}))
                case "view_test_structure":
                    return await ai_scriptless_manager.view_test_structure(args.get("test_id", ""))
                case "list_commands":
                    return await ai_scriptless_manager.list_commands(args.get("checkpoint", False))
                case "get_command_definitions":
                    return await ai_scriptless_manager.get_command_definitions(args.get("command_ids", []))
                case "add_command":
                    return await ai_scriptless_manager.add_command(
                        args.get("test_id", ""),
                        args.get("command_id", ""),
                        args.get("arguments"),
                        args.get("after_path"),
                        args.get("parent_path"),
                    )
                case "modify_command":
                    return await ai_scriptless_manager.modify_command(
                        args.get("test_id", ""),
                        args.get("step_path", ""),
                        args.get("arguments", {}),
                    )
                case "delete_command":
                    return await ai_scriptless_manager.delete_command(
                        args.get("test_id", ""),
                        args.get("step_path", ""),
                    )
                case "set_command_enabled":
                    return await ai_scriptless_manager.set_command_enabled(
                        args.get("test_id", ""),
                        args.get("step_path", ""),
                        args.get("enabled", True),
                    )
                case "save_test":
                    return await ai_scriptless_manager.save_test(
                        args.get("test_id", ""),
                        args.get("comment"),
                    )
                case "create_test":
                    return await ai_scriptless_manager.create_test(
                        args.get("name", ""),
                        args.get("folder", "My Folder"),
                        args.get("visibility", "PRIVATE"),
                    )
                case "save_test_as":
                    return await ai_scriptless_manager.save_test_as(
                        args.get("test_id", ""),
                        args.get("name", ""),
                        args.get("folder", "My Folder"),
                        args.get("visibility", "PRIVATE"),
                        args.get("comment"),
                    )
                case "add_logical_step":
                    return await ai_scriptless_manager.add_logical_step(
                        args.get("test_id", ""),
                        args.get("label"),
                        args.get("after_path"),
                        args.get("parent_path"),
                    )
                case "add_loop":
                    return await ai_scriptless_manager.add_loop(
                        args.get("test_id", ""),
                        args.get("count", 1),
                        args.get("after_path"),
                        args.get("parent_path"),
                    )
                case "add_condition":
                    return await ai_scriptless_manager.add_condition(
                        args.get("test_id", ""),
                        args.get("expression"),
                        args.get("label"),
                        args.get("after_path"),
                        args.get("parent_path"),
                    )
                case "set_condition_expression":
                    return await ai_scriptless_manager.set_condition_expression(
                        args.get("test_id", ""),
                        args.get("step_path", ""),
                        args.get("expression", ""),
                    )
                case "move_command":
                    return await ai_scriptless_manager.move_command(
                        args.get("test_id", ""),
                        args.get("step_path", ""),
                        args.get("after_path"),
                        args.get("parent_path"),
                    )
                case "delete_test":
                    return await ai_scriptless_manager.delete_test(args.get("test_id", ""))
                case "move_test":
                    return await ai_scriptless_manager.move_test(
                        args.get("test_id", ""),
                        args.get("folder", ""),
                        args.get("visibility"),
                    )
                case "list_snapshots":
                    return await ai_scriptless_manager.list_snapshots(args.get("test_id", ""))
                case "view_snapshot":
                    return await ai_scriptless_manager.view_snapshot(args.get("snapshot_id", ""))
                case "list_test_variables":
                    return await ai_scriptless_manager.list_test_variables(args.get("test_id", ""))
                case "add_test_variable":
                    return await ai_scriptless_manager.add_test_variable(
                        args.get("test_id", ""),
                        args.get("name", ""),
                        args.get("variable_type", "string"),
                        args.get("value", ""),
                        args.get("set_at_runtime", False),
                    )
                case "modify_test_variable":
                    return await ai_scriptless_manager.modify_test_variable(
                        args.get("test_id", ""),
                        args.get("name", ""),
                        args.get("value"),
                        args.get("variable_type"),
                        args.get("set_at_runtime"),
                    )
                case "delete_test_variable":
                    return await ai_scriptless_manager.delete_test_variable(
                        args.get("test_id", ""),
                        args.get("name", ""),
                    )
                case _:
                    return BaseResult(
                        error=f"Action {action} not found in AI Scriptless manager tool"
                    )
        except httpx.HTTPStatusError:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}"
            )
        except Exception:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}\n{SUPPORT_MESSAGE}"
            )
