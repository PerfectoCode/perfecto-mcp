import copy
import json
import uuid
from typing import Any, Optional
from urllib.parse import quote

from config import perfecto
from config.token import PerfectoToken
from models.result import BaseResult
from tools.utils import api_request


def build_item_key(visibility: str, folder: str, name: str) -> str:
    test_name = name if name.endswith(".xml") else f"{name}.xml"
    folder = folder.strip("/")
    return f"{visibility}:{folder}/{test_name}"


def split_item_key(item_key: str) -> tuple[str, str]:
    visibility, _, path = item_key.partition(":")
    if not path:
        raise ValueError(f"Invalid itemKey format (expected VISIBILITY:path): {item_key}")
    return visibility, path


def folder_type(visibility: str) -> str:
    if visibility in ("PRIVATE", "GROUP"):
        return visibility
    return "PUBLIC"


def test_file_name(item_key: str) -> str:
    _, path = split_item_key(item_key)
    return path.rsplit("/", 1)[-1]


def build_snapshot_search_body(test_id: str) -> dict[str, Any]:
    visibility, artifact_id = split_item_key(test_id)
    return {
        "repositoryType": "SCRIPTS",
        "keyDetails": {"artifactId": artifact_id, "version": "v0"},
        "folderType": folder_type(visibility),
    }


def build_move_test_body(
        test_id: str,
        folder: str,
        visibility: str,
        owner: str,
) -> dict[str, Any]:
    src_visibility, src_path = split_item_key(test_id)
    file_name = test_file_name(test_id)
    target_folder = folder.strip("/")
    target_directory = f"{target_folder}/{file_name}" if target_folder else file_name
    return {
        "copy": False,
        "directoryPath": src_path,
        "folderType": folder_type(src_visibility),
        "targetDirectoryPath": target_directory,
        "targetFolderType": folder_type(visibility),
        "repositoryType": "SCRIPTS",
        "owner": owner,
        "groupKey": None,
    }


def parse_command_id(command_id: str) -> tuple[str, str]:
    if command_id.startswith("ai_"):
        return "ai", command_id[3:]
    if "_" in command_id:
        command, subcommand = command_id.split("_", 1)
        return command, subcommand
    return command_id, ""


def element_type_for_command(command: str, subcommand: str) -> str:
    if command == "ai" and subcommand == "validation":
        return "Validation"
    if command == "checkpoint":
        return "Validation"
    return "Action"


def default_error_policy(element_type: str) -> str:
    return "IGNORE" if element_type == "Validation" else "ABORT"


def _make_argument(name: str, value: Any, data_source: str = "CONSTANT") -> dict[str, Any]:
    if data_source == "VARIABLE":
        data: dict[str, Any] = {
            "@type": "VariableArgumentData",
            "dataSource": "VARIABLE",
            "value": value,
        }
    else:
        data = {
            "@type": "ConstantArgumentData",
            "dataSource": "CONSTANT",
            "secured": False,
            "value": value,
        }
    return {"@type": "FunctionArgument", "name": name, "data": data}


def _default_arguments(command_id: str) -> dict[str, tuple[str, Any]]:
    defaults: dict[str, dict[str, tuple[str, Any]]] = {
        "ai_user-action": {
            "handsetId": ("VARIABLE", "DUT"),
            "action": ("CONSTANT", ""),
        },
        "ai_validation": {
            "handsetId": ("VARIABLE", "DUT"),
            "validation": ("CONSTANT", ""),
        },
        "ai_visual-comparison": {
            "handsetId": ("VARIABLE", "DUT"),
            "name": ("CONSTANT", ""),
        },
        "comment": {
            "text": ("CONSTANT", ""),
        },
        "wait": {
            "waitDuration": ("CONSTANT", "1"),
        },
        "handset_ready": {
            "handsetId": ("VARIABLE", "DUT"),
        },
        "touch_tap": {
            "handsetId": ("VARIABLE", "DUT"),
        },
        "checkpoint_text": {
            "handsetId": ("VARIABLE", "DUT"),
        },
        "checkpoint_image": {
            "handsetId": ("VARIABLE", "DUT"),
        },
    }
    return defaults.get(command_id, {"handsetId": ("VARIABLE", "DUT")})


def build_arguments(command_id: str, arguments: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, tuple[str, Any]] = _default_arguments(command_id)
    if arguments:
        for name, value in arguments.items():
            if isinstance(value, dict) and "data_source" in value:
                merged[name] = (value["data_source"], value.get("value"))
            else:
                merged[name] = ("CONSTANT", value)
    return [_make_argument(name, value, source) for name, (source, value) in merged.items()]


def build_flow_element(command_id: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    command, subcommand = parse_command_id(command_id)
    element_type = element_type_for_command(command, subcommand)
    return {
        "@type": element_type,
        "validations": [],
        "errorPolicy": default_error_policy(element_type),
        "command": command,
        "subcommand": subcommand,
        "arguments": build_arguments(command_id, arguments),
        "comment": None,
        "status": None,
        "active": True,
        "uuid": str(uuid.uuid4()),
    }


CONTAINER_TYPES = frozenset({"LogicalStep", "Loop", "Branch"})

VARIABLE_TYPE_ALIASES = {
    "string": "StringData",
    "secured_string": "StringData",
    "number": "IntegerData",
    "boolean": "BooleanData",
    "device": "HandsetData",
    "media": "MediaData",
    "datatable": "TableData",
}

SUPPORTED_VARIABLE_TYPES = frozenset({"string", "secured_string", "number", "boolean"})


def validate_variable_name(name: str) -> None:
    if not name or not name.strip():
        raise ValueError("name is required")
    if name[0].isdigit():
        raise ValueError("name cannot begin with a number")
    if not all(char.isalnum() or char == "_" for char in name):
        raise ValueError("name may contain only letters, numbers, and underscore")


def _coerce_variable_value(variable_type: str, value: Any) -> Any:
    if variable_type == "boolean":
        if isinstance(value, bool):
            return value
        normalized = str(value).lower()
        if normalized not in ("true", "false"):
            raise ValueError("boolean value must be true or false")
        return normalized == "true"
    if variable_type == "number":
        try:
            numeric = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("number value must be an integer") from exc
        return numeric
    return "" if value is None else str(value)


def build_variable_data(variable_type: str, name: str, value: Any) -> dict[str, Any]:
    if variable_type not in SUPPORTED_VARIABLE_TYPES:
        raise ValueError(
            f"Unsupported variable type: {variable_type}. "
            f"Supported types: {', '.join(sorted(SUPPORTED_VARIABLE_TYPES))}"
        )
    validate_variable_name(name)
    coerced_value = _coerce_variable_value(variable_type, value)
    data_type = VARIABLE_TYPE_ALIASES[variable_type]
    data: dict[str, Any] = {
        "@type": data_type,
        "description": None,
        "displayName": None,
        "name": name,
        "secured": variable_type == "secured_string",
        "value": coerced_value,
    }
    if data_type == "HandsetData":
        data["key"] = None
    if data_type == "TableData":
        data["columns"] = []
    return data


def build_variable_entry(
        name: str,
        variable_type: str,
        value: Any,
        set_at_runtime: bool = False,
) -> dict[str, Any]:
    return {
        "@type": "Parameter" if set_at_runtime else "Variable",
        "uuid": str(uuid.uuid4()),
        "data": build_variable_data(variable_type, name, value),
    }


def find_variable(script: dict[str, Any], variable_name: str) -> Optional[tuple[int, dict[str, Any]]]:
    for index, variable in enumerate(script.get("variables", [])):
        data = variable.get("data", {})
        if data.get("name") == variable_name:
            return index, variable
    return None


def list_script_variables(script: dict[str, Any]) -> list[dict[str, Any]]:
    return list(script.get("variables", []))


def add_script_variable(
        script: dict[str, Any],
        name: str,
        variable_type: str,
        value: Any,
        set_at_runtime: bool = False,
) -> dict[str, Any]:
    validate_variable_name(name)
    if find_variable(script, name):
        raise ValueError(f"variable already exists: {name}")
    if name == "DUT":
        raise ValueError("DUT is a test parameter, not a script variable")
    entry = build_variable_entry(name, variable_type, value, set_at_runtime)
    script.setdefault("variables", []).append(entry)
    return entry


def modify_script_variable(
        script: dict[str, Any],
        variable_name: str,
        value: Optional[Any] = None,
        variable_type: Optional[str] = None,
        set_at_runtime: Optional[bool] = None,
) -> dict[str, Any]:
    located = find_variable(script, variable_name)
    if located is None:
        raise ValueError(f"variable not found: {variable_name}")
    _, variable = located
    current_type = _variable_type_from_data(variable.get("data", {}))
    target_type = variable_type or current_type
    if target_type not in SUPPORTED_VARIABLE_TYPES:
        raise ValueError(
            f"Unsupported variable type: {target_type}. "
            f"Supported types: {', '.join(sorted(SUPPORTED_VARIABLE_TYPES))}"
        )
    current_value = variable.get("data", {}).get("value")
    target_value = current_value if value is None else value
    variable["data"] = build_variable_data(target_type, variable_name, target_value)
    if set_at_runtime is not None:
        variable["@type"] = "Parameter" if set_at_runtime else "Variable"
    return variable


def delete_script_variable(script: dict[str, Any], variable_name: str) -> None:
    located = find_variable(script, variable_name)
    if located is None:
        raise ValueError(f"variable not found: {variable_name}")
    index, _ = located
    script.get("variables", []).pop(index)


def _variable_type_from_data(data: dict[str, Any]) -> str:
    data_type = data.get("@type", "")
    if data_type == "StringData":
        return "secured_string" if data.get("secured") else "string"
    reverse = {
        "BooleanData": "boolean",
        "IntegerData": "number",
        "HandsetData": "device",
        "MediaData": "media",
        "TableData": "datatable",
    }
    return reverse.get(data_type, "string")


def build_branch(clause: str) -> dict[str, Any]:
    return {
        "@type": "Branch",
        "clause": clause,
        "flowElements": [],
        "numOfFlowElements": 0,
        "empty": True,
        "active": True,
        "comment": None,
        "status": None,
        "uuid": str(uuid.uuid4()),
    }


def build_logical_step(label: Optional[str] = None) -> dict[str, Any]:
    return {
        "@type": "LogicalStep",
        "flowElements": [],
        "active": True,
        "label": label or "",
        "comment": None,
        "status": None,
        "uuid": str(uuid.uuid4()),
    }


def build_loop(count: int = 1) -> dict[str, Any]:
    return {
        "@type": "Loop",
        "iterator": {"@type": "RepeatIterator", "count": count},
        "flowElements": [],
        "active": True,
        "comment": None,
        "status": None,
        "uuid": str(uuid.uuid4()),
    }


def build_if_statement(expression: Optional[str] = None, label: Optional[str] = None) -> dict[str, Any]:
    then_branch = build_branch("THEN")
    else_branch = build_branch("ELSE")
    statement: dict[str, Any] = {
        "@type": "IfStatement",
        "branches": [then_branch, else_branch],
        "thenClause": build_branch("THEN"),
        "elseClause": build_branch("ELSE"),
        "label": label or "",
        "numOfFlowElements": 3,
        "comment": None,
        "status": None,
        "active": True,
        "uuid": str(uuid.uuid4()),
    }
    if expression:
        statement["expression"] = expression
    return statement


def new_empty_script() -> dict[str, Any]:
    return {
        "@type": "Script",
        "parameters": [{
            "@type": "Parameter",
            "name": "DUT",
            "data": {
                "@type": "HandsetData",
                "key": None,
                "value": None,
                "secured": False,
                "description": None,
                "displayName": None,
                "name": "DUT",
            },
        }],
        "info": {"@type": "ScriptInfo", "description": "", "modelVersion": "1.0"},
        "options": {"@type": "ScriptOptions", "automaticAllocation": True},
        "variables": [],
        "flowElements": [],
        "numOfFlowElements": 0,
    }


def assign_uuids(element: dict[str, Any]) -> None:
    if element.get("uuid") is None:
        element["uuid"] = str(uuid.uuid4())
    for child in element.get("flowElements", []):
        assign_uuids(child)
    if element.get("@type") == "IfStatement":
        for branch in element.get("branches", []):
            assign_uuids(branch)
            for child in branch.get("flowElements", []):
                assign_uuids(child)
        for clause_key in ("thenClause", "elseClause"):
            clause = element.get(clause_key)
            if clause:
                assign_uuids(clause)
                for child in clause.get("flowElements", []):
                    assign_uuids(child)


def assign_uuids_to_script(script: dict[str, Any]) -> None:
    for element in script.get("flowElements", []):
        assign_uuids(element)


def _iter_element_locations(flow_elements: list[dict[str, Any]]):
    for index, element in enumerate(flow_elements):
        yield flow_elements, index, element
        for child_list, child_index, child in _iter_element_locations(element.get("flowElements", [])):
            yield child_list, child_index, child
        if element.get("@type") == "IfStatement":
            for branch in element.get("branches", []):
                for child_list, child_index, child in _iter_element_locations(branch.get("flowElements", [])):
                    yield child_list, child_index, child


def find_element_by_uuid(script: dict[str, Any], step_uuid: str) -> Optional[tuple[list[dict[str, Any]], int, dict[str, Any]]]:
    for elements, index, element in _iter_element_locations(script.get("flowElements", [])):
        if element.get("uuid") == step_uuid:
            return elements, index, element
    return None


def find_container_by_uuid(script: dict[str, Any], step_uuid: str) -> Optional[dict[str, Any]]:
    located = find_element_by_uuid(script, step_uuid)
    if located:
        _, _, element = located
        return element
    return None


def update_flow_element_counts(script: dict[str, Any]) -> None:
    script["numOfFlowElements"] = len(script.get("flowElements", []))


def insert_flow_element(
        script: dict[str, Any],
        element: dict[str, Any],
        after_uuid: Optional[str] = None,
        parent_uuid: Optional[str] = None,
) -> None:
    if parent_uuid:
        parent = find_container_by_uuid(script, parent_uuid)
        if parent is None:
            raise ValueError(f"parent_uuid not found: {parent_uuid}")
        if parent.get("@type") not in CONTAINER_TYPES:
            raise ValueError(f"parent_uuid must reference a container (LogicalStep, Loop, Branch): {parent_uuid}")
        parent.setdefault("flowElements", []).append(element)
        return

    flow_elements = script.setdefault("flowElements", [])
    if after_uuid:
        located = find_element_by_uuid(script, after_uuid)
        if located is None:
            raise ValueError(f"after_uuid not found: {after_uuid}")
        elements, index, _ = located
        elements.insert(index + 1, element)
    else:
        flow_elements.append(element)
    update_flow_element_counts(script)


def update_element_arguments(element: dict[str, Any], arguments: dict[str, Any]) -> None:
    existing = {argument["name"]: argument for argument in element.get("arguments", [])}
    for name, value in arguments.items():
        if isinstance(value, dict) and "data_source" in value:
            source = value["data_source"]
            argument_value = value.get("value")
        else:
            source = "CONSTANT"
            argument_value = value
        existing[name] = _make_argument(name, argument_value, source)
    element["arguments"] = list(existing.values())


def delete_element_by_uuid(script: dict[str, Any], step_uuid: str) -> None:
    located = find_element_by_uuid(script, step_uuid)
    if located is None:
        raise ValueError(f"uuid not found: {step_uuid}")
    elements, index, _ = located
    elements.pop(index)
    update_flow_element_counts(script)


def set_element_enabled(script: dict[str, Any], step_uuid: str, enabled: bool) -> None:
    located = find_element_by_uuid(script, step_uuid)
    if located is None:
        raise ValueError(f"uuid not found: {step_uuid}")
    _, _, element = located
    element["active"] = enabled


def set_condition_expression(script: dict[str, Any], step_uuid: str, expression: str) -> None:
    located = find_element_by_uuid(script, step_uuid)
    if located is None:
        raise ValueError(f"uuid not found: {step_uuid}")
    _, _, element = located
    if element.get("@type") != "IfStatement":
        raise ValueError(f"step_uuid must reference an IfStatement: {step_uuid}")
    element["expression"] = expression


def move_element_by_uuid(
        script: dict[str, Any],
        step_uuid: str,
        after_uuid: Optional[str] = None,
        parent_uuid: Optional[str] = None,
) -> None:
    located = find_element_by_uuid(script, step_uuid)
    if located is None:
        raise ValueError(f"uuid not found: {step_uuid}")
    source_list, source_index, element = located
    source_list.pop(source_index)

    if parent_uuid:
        parent = find_container_by_uuid(script, parent_uuid)
        if parent is None:
            raise ValueError(f"parent_uuid not found: {parent_uuid}")
        if parent.get("@type") not in CONTAINER_TYPES:
            raise ValueError(f"parent_uuid must reference a container (LogicalStep, Loop, Branch): {parent_uuid}")
        parent.setdefault("flowElements", []).append(element)
    elif after_uuid:
        target = find_element_by_uuid(script, after_uuid)
        if target is None:
            raise ValueError(f"after_uuid not found: {after_uuid}")
        target_list, target_index, _ = target
        if target_list is source_list and source_index < target_index:
            target_index -= 1
        target_list.insert(target_index + 1, element)
    else:
        script.setdefault("flowElements", []).append(element)
    update_flow_element_counts(script)


async def fetch_script_payload(token: PerfectoToken, test_id: str) -> BaseResult:
    script_url = perfecto.get_ai_scriptless_api_url(token.cloud_name)
    script_url = script_url + f"/script?itemKey={quote(test_id, safe='')}"
    return await api_request(token, "GET", endpoint=script_url)


async def fetch_current_username(token: PerfectoToken) -> Optional[str]:
    user_url = perfecto.get_user_management_api_url(token.cloud_name) + "/current"
    result = await api_request(token, "GET", endpoint=user_url)
    if result.error or not isinstance(result.result, dict):
        return None
    return result.result.get("username") or result.result.get("userId")


async def persist_script(
        token: PerfectoToken,
        item_key: str,
        script: dict[str, Any],
        saved_script: Optional[dict[str, Any]] = None,
        snapshot_comment: Optional[str] = None,
) -> BaseResult:
    working_script = copy.deepcopy(script)
    baseline_script = copy.deepcopy(saved_script or script)
    assign_uuids_to_script(working_script)
    assign_uuids_to_script(baseline_script)
    update_flow_element_counts(working_script)

    draft_url = perfecto.get_ai_scriptless_draft_api_url(token.cloud_name)
    draft_data = json.dumps({
        "unsavedScript": working_script,
        "savedScript": baseline_script,
    })
    draft_result = await api_request(
        token,
        "POST",
        endpoint=draft_url,
        json={
            "path": item_key,
            "type": "MOBILE_IDE_SCRIPT",
            "data": draft_data,
        },
    )
    if draft_result.error:
        return draft_result
    draft_key = draft_result.result.get("key")
    if not draft_key:
        return BaseResult(error="Draft creation failed: missing draft key in response")

    script_url = perfecto.get_ai_scriptless_api_url(token.cloud_name) + "/script"
    save_body: dict[str, Any] = {
        "script": working_script,
        "itemKey": item_key,
        "draftKey": draft_key,
    }
    if snapshot_comment:
        save_body["snapshotComment"] = snapshot_comment
    save_result = await api_request(
        token,
        "POST",
        endpoint=script_url,
        json=save_body,
    )
    if save_result.error:
        return save_result

    result: dict[str, Any] = {
        "item_key": item_key,
        "draft_key": draft_key,
        "status": save_result.result.get("status", "success") if isinstance(save_result.result, dict) else "success",
        "flow_element_count": len(working_script.get("flowElements", [])),
    }
    if snapshot_comment:
        result["snapshot_comment"] = snapshot_comment
    result["notes"] = [
        "Perfecto adds a new snapshot history entry on every script save.",
        "Use list_snapshots with test_id to see version history after saving.",
    ]
    if snapshot_comment:
        result["notes"].append(
            "The comment labels the '<current>' entry in list_snapshots (UI: Save with comment)."
        )
    else:
        result["notes"].append(
            "Saving without comment still creates a history entry; pass comment to label the current version."
        )
    return BaseResult(result=result)


async def load_and_mutate(
        token: PerfectoToken,
        test_id: str,
        mutator,
) -> BaseResult:
    payload_result = await fetch_script_payload(token, test_id)
    if payload_result.error:
        return payload_result
    payload = payload_result.result
    script = copy.deepcopy(payload.get("script", {}))
    saved_script = copy.deepcopy(payload.get("script", {}))
    try:
        mutator(script)
    except ValueError as exc:
        return BaseResult(error=str(exc))
    return await persist_script(token, test_id, script, saved_script)
