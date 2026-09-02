import copy
import json
from typing import Optional, Any, Dict
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import Context
from pydantic import Field

from config import perfecto
from config.perfecto import TOOLS_PREFIX, SUPPORT_MESSAGE
from config.token import PerfectoToken, token_verify
from formatters.ai_scriptless import format_ai_scriptless_tests, \
    format_ai_scriptless_tests_filter_values, command_selection_policy_info, \
    format_command_catalog, format_command_definitions, format_snapshots_list, \
    format_step_detail, format_test_structure, format_test_variables
from models.manager import Manager
from models.result import BaseResult, PaginationResult
from telemetry import run_tool
from tools.ai_scriptless_script import (
    add_script_variable,
    build_flow_element,
    build_if_statement,
    build_item_key,
    build_logical_step,
    build_loop,
    build_move_test_body,
    build_snapshot_search_body,
    command_id_from_element,
    command_contract,
    delete_script_variable,
    delete_element_by_path,
    empty_mandatory_note,
    fetch_script_payload,
    find_element_by_path,
    find_step_path_for_element,
    insert_flow_element,
    bindable_values,
    describe_bindable_values,
    list_script_variables,
    variable_type_label,
    load_and_mutate,
    modify_script_variable,
    move_element_by_path,
    new_empty_script,
    normalize_if_statement_aliases,
    persist_script,
    script_write_lock,
    find_condition_statement,
    set_element_error_policy,
    set_element_enabled,
    split_item_key,
    item_key_file_name,
    format_test_ui_location,
    update_element_arguments,
    validate_argument_names,
    validate_argument_values,
    validate_variable_bindings,
)
from tools.ai_scriptless.definitions import SUPPORTED_ERROR_POLICIES
from tools.utils import api_request, format_sanitized_traceback, normalize_action_args

STEP_PATH_REFRESH_NOTES = [
    "step_path values are dot-separated positional paths (e.g. 0, 2.0, 5.b0.1); Perfecto does not persist them.",
    "After this operation, step paths may have changed. Call view_test_structure before the next edit; "
    "do not reuse step_path values from this response.",
]

CONDITION_STATEMENT_HINT = (
    "A condition has no expression: the branch taken depends on the result of the step right "
    "before it, which must carry errorPolicy CATCH (the UI shows that step as the condition's "
    "'Statement'). Add the deciding command before the condition and mark it with "
    "set_command_error_policy(error_policy='CATCH'). An expression is dropped by Perfecto."
)

CMD_ARGUMENTS_COLLISION_HINT = (
    "The ai_user-action command declares a parameter named 'action', which collides with the action key "
    "of this tool: command arguments must stay nested inside 'cmd_arguments', never flattened into args. "
    "Example: {\"action\": \"add_command\", \"args\": {\"test_id\": \"...\", "
    "\"command_id\": \"ai_user-action\", \"cmd_arguments\": {\"action\": \"Tap on the Login button\"}}}."
)


def _command_arguments(args: Dict[str, Any]) -> Any:
    """Prefer cmd_arguments; accept arguments for older clients that used that key."""
    return args.get("cmd_arguments") or args.get("arguments")


def _unknown_action_error(action: str, args: Dict[str, Any]) -> str:
    error = f"Action {action} not found in AI Scriptless manager tool"
    # A command argument flattened to the top level overwrites the dispatcher action with free text.
    if args.get("command_id") or " " in action:
        error = f"{error}. {CMD_ARGUMENTS_COLLISION_HINT}"
    return error


def _append_step_path_refresh_notes(result: BaseResult) -> BaseResult:
    if result.error or not isinstance(result.result, dict):
        return result
    notes = result.result.setdefault("notes", [])
    for note in STEP_PATH_REFRESH_NOTES:
        if note not in notes:
            notes.append(note)
    return result


def _append_ui_access_info(
        result: BaseResult,
        cloud_name: str,
        test_id: Optional[str] = None,
) -> BaseResult:
    if result.error:
        return result
    lab_url = perfecto.get_ai_scriptless_lab_url(cloud_name)
    lines = [f"AI Scriptless UI (no per-test deep link): [{lab_url}]({lab_url})"]
    if test_id:
        lines.append(
            "If you need to open it in the UI: Tests → Open or Manage tests, then navigate to "
            f"{format_test_ui_location(test_id)}"
        )
    result.append_info(lines)
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

        items = tests_result.result or []
        page_result = PaginationResult(
            items=items,
            count=len(items),
            page=page_index,
            offset=skip,
            next_offset=skip + page_size,
            has_more=page_size - len(items) <= 0,
        )

        result = BaseResult(
            result=page_result,
            error=tests_result.error,
            warning=tests_result.warning,
            info=tests_result.info,
        )
        return _append_ui_access_info(result, self.token.cloud_name)

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
        result = await api_request(self.token, "GET", endpoint=commands_url,
                                   result_formatter=format_command_catalog)
        if not result.error:
            result.append_info(command_selection_policy_info())
        return result

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
        result = await api_request(self.token, "GET", endpoint=script_url,
                                 result_formatter=format_test_structure,
                                 result_formatter_params={"item_key": test_id})
        return _append_ui_access_info(result, self.token.cloud_name, test_id)

    @token_verify
    async def view_test_step(self, test_id: str, step_path: str) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required (itemKey from list_tests)")
        if not step_path:
            return BaseResult(error="step_path is required (from view_test_structure)")

        payload_result = await fetch_script_payload(self.token, test_id)
        if payload_result.error:
            return payload_result
        payload = payload_result.result if isinstance(payload_result.result, dict) else {}
        script = copy.deepcopy(payload.get("script", {}))
        normalize_if_statement_aliases(script)
        located = find_element_by_path(script, step_path)
        if located is None:
            return BaseResult(error=f"step_path not found: {step_path} (call view_test_structure)")
        _, _, element = located

        detail = format_step_detail(
            element,
            item_key=test_id,
            step_path=step_path,
            # The script payload already carries the definitions of the commands it uses.
            command_definitions=payload.get("commandDefinitions"),
            statement_step_path=find_condition_statement(script, step_path),
        )
        if detail.type == "IfStatement" and detail.statement_step_path is None:
            detail.notes.append(CONDITION_STATEMENT_HINT)
        return _append_ui_access_info(BaseResult(result=detail), self.token.cloud_name, test_id)

    @token_verify
    async def add_command(
            self,
            test_id: str,
            command_id: str,
            cmd_arguments: Optional[dict[str, Any]] = None,
            after_path: Optional[str] = None,
            parent_path: Optional[str] = None,
    ) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if not command_id:
            return BaseResult(error="command_id is required (from list_commands)")

        contract = await command_contract(self.token, command_id)
        names_error = validate_argument_names(command_id, cmd_arguments, contract)
        if names_error:
            return BaseResult(error=names_error)
        values_error = validate_argument_values(command_id, cmd_arguments, contract)
        if values_error:
            return BaseResult(error=values_error)

        element = build_flow_element(command_id, cmd_arguments, contract)
        inserted_path: dict[str, Optional[str]] = {"step_path": None}

        def mutator(script: dict[str, Any]) -> None:
            # Variable bindings need the script: the variable must exist with a matching type.
            bindings_error = validate_variable_bindings(command_id, cmd_arguments, contract, script)
            if bindings_error:
                raise ValueError(bindings_error)
            insert_flow_element(script, element, after_path=after_path, parent_path=parent_path)
            inserted_path["step_path"] = find_step_path_for_element(script, element)

        result = await load_and_mutate(self.token, test_id, mutator)
        if result.error:
            return result
        result.result["step_path"] = inserted_path["step_path"]
        result.result["command_id"] = command_id
        empty_note = empty_mandatory_note(command_id, cmd_arguments, contract)
        if empty_note:
            result.result.setdefault("notes", []).append(empty_note)
        return _append_step_path_refresh_notes(result)

    @token_verify
    async def modify_command(self, test_id: str, step_path: str, cmd_arguments: dict[str, Any]) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if not step_path:
            return BaseResult(error="step_path is required (from view_test_structure)")
        if not cmd_arguments:
            return BaseResult(error="cmd_arguments is required")

        async def mutator(script: dict[str, Any]) -> None:
            located = find_element_by_path(script, step_path)
            if located is None:
                raise ValueError(f"step_path not found: {step_path}")
            _, _, element = located
            # command_id is only known after locating the step, so validation happens here.
            command_id = command_id_from_element(element)
            contract = await command_contract(self.token, command_id)
            names_error = validate_argument_names(command_id, cmd_arguments, contract)
            if names_error:
                raise ValueError(names_error)
            values_error = validate_argument_values(command_id, cmd_arguments, contract)
            if values_error:
                raise ValueError(values_error)
            bindings_error = validate_variable_bindings(command_id, cmd_arguments, contract, script)
            if bindings_error:
                raise ValueError(bindings_error)
            update_element_arguments(element, cmd_arguments, contract)

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
        result = await persist_script(self.token, item_key, script)
        return _append_ui_access_info(result, self.token.cloud_name, item_key)

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
        result = _append_step_path_refresh_notes(
            await persist_script(self.token, item_key, script, snapshot_comment=comment)
        )
        return _append_ui_access_info(result, self.token.cloud_name, item_key)

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
            variable: Optional[str] = None,
    ) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if not variable and count < 1:
            return BaseResult(error="count must be at least 1")

        if variable:
            # The UI only offers number variables here, so check before writing.
            payload_result = await fetch_script_payload(self.token, test_id)
            if payload_result.error:
                return payload_result
            script = payload_result.result.get("script", {}) if payload_result.result else {}
            bindable = bindable_values(script)
            data = bindable.get(variable)
            if data is None:
                return BaseResult(
                    error=(
                        f"variable '{variable}' is not defined on this test. "
                        f"Defined: {describe_bindable_values(script)}."
                    )
                )
            if variable_type_label(data) != "number":
                return BaseResult(
                    error=(
                        f"a loop counts with a number variable; '{variable}' is a "
                        f"{variable_type_label(data)}."
                    )
                )

        element = build_loop(count, variable)
        result = await self._add_structure(test_id, element, "Loop", after_path, parent_path)
        if not result.error:
            if variable:
                result.result["variable"] = variable
            else:
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
        if expression:
            return BaseResult(error=CONDITION_STATEMENT_HINT)
        element = build_if_statement(label)
        result = await self._add_structure(test_id, element, "IfStatement", after_path, parent_path)
        if not result.error:
            result.result.setdefault("notes", []).append(CONDITION_STATEMENT_HINT)
        return result

    @token_verify
    async def set_command_error_policy(self, test_id: str, step_path: str, error_policy: str) -> BaseResult:
        if not test_id:
            return BaseResult(error="test_id is required")
        if not step_path:
            return BaseResult(error="step_path is required (from view_test_structure)")
        policy = str(error_policy or "").upper()
        if policy not in SUPPORTED_ERROR_POLICIES:
            return BaseResult(
                error=(
                    f"error_policy must be one of {', '.join(sorted(SUPPORTED_ERROR_POLICIES))}, "
                    f"got {error_policy!r}."
                )
            )

        def mutator(script: dict[str, Any]) -> None:
            set_element_error_policy(script, step_path, policy)

        result = await load_and_mutate(self.token, test_id, mutator)
        if result.error:
            return result
        result.result["step_path"] = step_path
        result.result["error_policy"] = policy
        if policy == "CATCH":
            result.result.setdefault("notes", []).append(
                "This step now feeds the condition that follows it; the UI shows it as that "
                "condition's Statement."
            )
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
        move_url = perfecto.get_repository_management_api_url(self.token.cloud_name) + "/artifacts"
        body = build_move_test_body(test_id, folder, target_visibility)
        result = await api_request(self.token, "PATCH", endpoint=move_url, json=body)
        if result.error:
            return result
        target_item_key = build_item_key(
            target_visibility,
            folder,
            item_key_file_name(test_id).removesuffix(".xml"),
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
        # Runtime parameters live in parameters[] and plain variables in variables[]; the UI
        # dialog lists both, so reading only one array hides half the declarations.
        variables = format_test_variables(list_script_variables(script))
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

        stored_value = value
        if variable_type == "secured_string" and value:
            encrypted = await self._encrypt_secured_value(value)
            if encrypted.error:
                return encrypted
            stored_value = encrypted.result

        def mutator(script: dict[str, Any]) -> None:
            add_script_variable(script, name, variable_type, stored_value, set_at_runtime)

        result = await load_and_mutate(self.token, test_id, mutator)
        if result.error:
            return result
        result.result["name"] = name
        result.result["type"] = variable_type
        result.result["set_at_runtime"] = set_at_runtime
        if variable_type == "secured_string":
            # Never echo either the plaintext or the ciphertext back.
            result.result["value"] = "<secured>"
        return result

    async def _encrypt_secured_value(self, value: Any) -> BaseResult:
        """Encrypt through the same endpoint the UI's lock button calls."""
        encrypt_url = perfecto.get_ai_scriptless_api_url(self.token.cloud_name)
        encrypt_url = encrypt_url + f"/script/variable/encrypt?value={quote(str(value), safe='')}"
        result = await api_request(self.token, "GET", endpoint=encrypt_url)
        if result.error:
            return BaseResult(error=f"Could not encrypt the secured value: {result.error}")
        ciphertext = result.result
        if isinstance(ciphertext, dict):
            ciphertext = ciphertext.get("value") or ciphertext.get("result")
        if not isinstance(ciphertext, str) or not ciphertext:
            return BaseResult(
                error="Could not encrypt the secured value: unexpected response from Perfecto"
            )
        return BaseResult(result=ciphertext)

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

        stored_value = value
        if variable_type == "secured_string" and value is not None:
            encrypted = await self._encrypt_secured_value(value)
            if encrypted.error:
                return encrypted
            stored_value = encrypted.result

        def mutator(script: dict[str, Any]) -> None:
            modify_script_variable(script, name, stored_value, variable_type, set_at_runtime)

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
- view_test_step: View the full configuration of one step (view_test_structure is the high-level tree; this is the detail).
    Returns every persisted argument with its current value and data_source, joined with what the command declares
    (parameter_type, mandatory, allowed_values, value_range, allowed_data_sources), plus unset_parameters: the declared
    parameters the step does not set yet. Read it before modify_command to know the exact keys and accepted values.
    Containers also report label, expression, loop_count and the step_path of their direct children.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        step_path (str): Step path from view_test_structure (e.g. 0, 2.0, 5.b0.1).
- list_commands: List available AI Scriptless commands from the command repository.
    Returns the catalog in result and command selection policy in info (read info before add_command when authoring tests).
    args(dict): Dictionary with the following optional parameters:
        checkpoint (bool, default=false): If true, list checkpoint commands only.
- get_command_definitions: Get parameter definitions for one or more commands.
    Returns mandatory_parameters and optional_parameters: these names are exactly the keys to use
    in cmd_arguments on add_command and modify_command (parameter = the declaration, argument = the value you set).
    args(dict): Dictionary with the following required parameters:
        command_ids (list[str]): Command IDs from list_commands (typically ai_user-action, ai_validation, ai_visual-comparison).
- add_command: Add a command to a test and persist it.
    args(dict): Dictionary with the following parameters:
        test_id (str, required): Test itemKey from list_tests.
        command_id (str, required): Command ID from list_commands.
        cmd_arguments (dict, optional): Command argument names to values. Keys must be parameter names from
            get_command_definitions (mandatory_parameters / optional_parameters); undeclared keys are rejected.
            Values are constants by default. To point an argument at a script variable instead of a constant,
            pass {"data_source": "VARIABLE", "value": "<variable name>"} (see list_test_variables), or bind it to
            a DataTable column with {"data_source": "DATATABLE", "table_name": "<table>", "column": "<column>"}.
            A parameter only accepts the data sources listed in allowed_data_sources by view_test_step.
            A multivalued parameter (max_occurrences > 1, e.g. the 'value' of text_concat which needs at least
            two) takes a list, in order, each item a constant or a binding of its own:
            {"value": ["Hello", {"data_source": "VARIABLE", "value": "name"}]}. Sending a multivalued parameter
            replaces its whole list, the way the UI's row editor does.
            Never flatten these keys to the top level of args: ai_user-action declares a parameter named
            'action', which would collide with the action key of this tool. Always nest them in cmd_arguments,
            e.g. {"action": "add_command", "args": {"test_id": "...", "command_id": "ai_user-action",
            "cmd_arguments": {"action": "Tap on the Login button"}}}.
            'arguments' is accepted as a backward-compatible alias for cmd_arguments.
        after_path (str, optional): Insert after this step (step_path from view_test_structure).
        parent_path (str, optional): Insert inside a container (step_path of LogicalStep, Loop, or Branch).
- modify_command: Update command arguments and persist.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        step_path (str): Step path from view_test_structure (e.g. 0, 2.0, 5.b0.1).
        cmd_arguments (dict): Argument names to new values. Merge semantics: only the arguments you send are
            replaced, the rest keep their current value, and arguments cannot be removed (delete_command removes
            the whole step). Same key rules as add_command (declared parameter names, optional data_source form).
            'arguments' is accepted as a backward-compatible alias for cmd_arguments.
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
        count (int, default=1): How many times to repeat (ignored when variable is given).
        variable (str, optional): Name of a number variable whose value decides the iterations,
            instead of a fixed count (UI: the Loop editor's Variable mode).
        after_path (str, optional): Insert after this step path.
        parent_path (str, optional): Insert inside a container step path.
- add_condition: Add an IfStatement condition with Then/Else branches and persist.
    A condition has no expression. The branch taken depends on the result of the step immediately
    before it, which must carry errorPolicy CATCH; the UI shows that step as the condition's
    'Statement'. So: add the deciding command (typically a validation or checkpoint), mark it with
    set_command_error_policy(error_policy='CATCH'), then add the condition after it.
    args(dict): Dictionary with the following parameters:
        test_id (str, required): Test itemKey from list_tests.
        label (str, optional): Condition label.
        after_path (str, optional): Insert after this step path.
        parent_path (str, optional): Insert inside a container step path.
- set_command_error_policy: Set what a step does when it fails ('On-fail Result' in the UI) and persist.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        step_path (str): Step path of a command (not a container) from view_test_structure.
        error_policy (str, values=['ABORT', 'IGNORE', 'BREAK', 'CONTINUE', 'CATCH']): ABORT ends the run,
            IGNORE reports the failure and goes on, BREAK and CONTINUE act on the enclosing loop (abort
            outside one), CATCH feeds the result to the condition that follows the step.
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
        folder (str): Target folder path without visibility prefix (e.g. 'My Folder', 'MCP Archive', or 'My Folder/SubFolder'). The test file keeps its name. If the path does not exist, the API creates the nested folder segments automatically (the new folder may not appear as a CONTAINER in list_tests until it contains tests).
        visibility (str, optional): Target visibility; defaults to the source test visibility.
    Returns source_item_key and target_item_key; use target_item_key for view_test_structure, execute_test, and other actions after the move.
- list_snapshots: List snapshot history for a test (includes '<current>' marker plus UUID historical versions).
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
    Returns notes explaining that every save adds history entries and how '<current>' vs UUID keys work.
- view_snapshot: View the hierarchical structure of a historical snapshot (same format as view_test_structure).
    args(dict): Dictionary with the following required parameters:
        snapshot_id (str): UUID key from list_snapshots (not '<current>'; use view_test_structure for the live script).
- list_test_variables: List everything the test declares, exactly as the UI's Configure test variables dialog:
    runtime parameters first (set_at_runtime=true, including the DUT device parameter), then plain variables.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
- add_test_variable: Add a script variable or runtime parameter and persist.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        name (str): Variable name (letters, numbers, underscore; cannot start with a number). Must be unique
            across runtime parameters and variables alike; Perfecto rejects a name declared twice.
        variable_type (str, default='string', values=['string', 'secured_string', 'number', 'boolean']): Variable type.
        value (any, default=''): Variable value. For secured_string, pass the plaintext: it is encrypted
            through Perfecto before being stored (the UI's lock button) and never echoed back.
        set_at_runtime (bool, default=false): True makes it a runtime variable: the stored value is only the
            default, it is supplied when the run starts (UI: the 'Set at runtime' checkbox, then the 'Enter
            runtime values' dialog; execute_test is that same channel, the way DUT receives its device) and it
            may change during the execution — a command parameter declared inOutBehavior OUT writes its result
            into the variable it names. False makes the value constant for the whole run.
- modify_test_variable: Update a script variable and persist.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        name (str): Existing variable name (runtime parameters included; DUT cannot be modified).
        value (any, optional): New value.
        variable_type (str, optional): New type (string, secured_string, number, boolean).
        set_at_runtime (bool, optional): Toggle between runtime parameter and variable.
- delete_test_variable: Remove a script variable and persist.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test itemKey from list_tests.
        name (str): Variable name to delete (runtime parameters included; DUT cannot be deleted).
Hints:
- LICENSE: AI Scriptless actions require a Perfecto AI license on your cloud (administrator opt-in via feature toggle). Without it, AI commands and related MCP operations will not work. Desktop web test authoring additionally requires the Desktop Web license.
- COVERAGE: DataTables, Scheduler (scheduled jobs), Embedded tests, and other advanced UI capabilities (folder management, rename test, restore snapshot, download as Appium, AI Assistant, Object Spy, per-step error policy, etc.) are not yet supported by this MCP tool. 
- HELP: For product behavior and workarounds, use the perfecto_help tool: Filter by category_id='perfecto', subcategory_id_list=['ide'].
- UI_ACCESS: No per-test URL exists. Only UI entry: cloud_url/lab/scriptless-mobile/ (cloud_url from perfecto_user read_user). For debugging or unsupported MCP tasks, link the lab URL and tell the user to open the test via Tests → Open or Manage tests using the folder tree and test name from list_tests (itemKey is MCP-only; the UI shows folders and names, not itemKey). Never invent other scriptless URLs.
- When authoring or editing test steps, call list_commands first and follow the command selection policy in the info field.
- Before editing an existing step, call view_test_step with its step_path: view_test_structure is a high-level tree and
  does not show argument values, so it is not enough to know what to change.
- cmd_arguments keys are validated against the command definitions before saving: an undeclared name is rejected with
  the list of valid parameter names instead of being persisted as a step argument that Perfecto ignores at runtime.
- Values are validated too: a number outside the declared range, a value outside allowed_values, a non-boolean on a
  boolean parameter, or a data_source the parameter does not accept are all rejected with the accepted options.
  Numbers and booleans are normalized to the spelling Perfecto persists, so passing 30 or "30" is equivalent.
- A VARIABLE binding is checked against the test: the variable must exist and its type must match the parameter
  (a string variable cannot feed a Number parameter), the same rule the UI enforces by only offering compatible
  variables. The error lists the variables the test defines with their types.
- A step's failure semantics also come from the command definition: Action steps abort the test (ABORT) while
  Validation steps are only reported (IGNORE). No need to set it, add_command applies what the command declares.
- step_path is a dot-separated positional path without spaces (0-based indices; b0=Then branch, b1=Else). Example: root step 3 is "3"; first step inside Then of condition at 5 is "5.b0.0". Perfecto does not persist paths; they change when steps are inserted, moved, or deleted. Always call view_test_structure before the next structure edit; do not reuse step_path from a previous mutation response.
- Use parent_path on add_command with the step_path of a LogicalStep, Loop, or Branch from view_test_structure.
- Use add_logical_step, add_loop, and add_condition to build control-flow structures matching the UI toolbar Group, Loop, and Condition actions.
- A declaration lives in one of two places depending on 'Set at runtime': runtime parameters in script.parameters[]
  (as Parameter, where DUT lives) and fixed-value variables in script.variables[] (as Variable). The variable actions
  cover both, and toggling set_at_runtime moves the declaration from one to the other.
- A VARIABLE binding on cmd_arguments can target any of them as long as the type matches the parameter
  (a Number parameter needs a number variable), which is what the UI's variable picker filters by.
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
            arguments: Dict[str, Any] = Field(description="Dictionary with arguments", default=None),
            ctx: Context = Field(description="Context object providing access to MCP capabilities")
    ) -> BaseResult:
        action, args = normalize_action_args(arguments)
        ai_scriptless_manager = AiScriptlessManager(token, ctx)

        async def _dispatch():
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
                case "view_test_step":
                    return await ai_scriptless_manager.view_test_step(
                        args.get("test_id", ""),
                        args.get("step_path", ""),
                    )
                case "list_commands":
                    return await ai_scriptless_manager.list_commands(args.get("checkpoint", False))
                case "get_command_definitions":
                    return await ai_scriptless_manager.get_command_definitions(args.get("command_ids", []))
                case "add_command":
                    return await ai_scriptless_manager.add_command(
                        args.get("test_id", ""),
                        args.get("command_id", ""),
                        _command_arguments(args),
                        args.get("after_path"),
                        args.get("parent_path"),
                    )
                case "modify_command":
                    return await ai_scriptless_manager.modify_command(
                        args.get("test_id", ""),
                        args.get("step_path", ""),
                        _command_arguments(args) or {},
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
                        args.get("variable"),
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
                    # Kept so an agent that learned the old action gets the mechanism, not silence.
                    return BaseResult(error=CONDITION_STATEMENT_HINT)
                case "set_command_error_policy":
                    return await ai_scriptless_manager.set_command_error_policy(
                        args.get("test_id", ""),
                        args.get("step_path", ""),
                        args.get("error_policy", ""),
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
                    return BaseResult(error=_unknown_action_error(action, args))

        try:
            return await run_tool(f"{TOOLS_PREFIX}_ai_scriptless", action, ctx, _dispatch)
        except httpx.HTTPStatusError:
            return BaseResult(
                error=f"Error: {format_sanitized_traceback()}"
            )
        except Exception:
            return BaseResult(
                error=f"Error: {format_sanitized_traceback()}\n{SUPPORT_MESSAGE}"
            )
