from typing import List, Any, Optional

import copy

from models.ai_scriptless import (
    CommandCatalogEntry,
    CommandDefinitionSummary,
    ScriptFlowElement,
    ScriptParameter,
    ScriptStepArgument,
    ScriptStepDetail,
    ScriptStepParameter,
    ScriptVariableSummary,
    SnapshotListResult,
    SnapshotSummary,
    TestStructure,
)
from tools.ai_scriptless.definitions import (
    parameter_label,
    restriction_allowed_values,
    restriction_range,
)
from tools.ai_scriptless.elements import normalize_if_statement_aliases

PRIMARY_AI_COMMAND_IDS = (
    "ai_user-action",
    "ai_validation",
    "ai_visual-comparison",
)


def command_selection_policy_info() -> List[str]:
    """Context returned with list_commands so agents load policy when choosing command_ids."""
    return [
        "Command selection policy (when authoring tests with add_command / modify_command):",
        "Default: use only these primary AI command_ids: "
        + ", ".join(PRIMARY_AI_COMMAND_IDS) + ".",
        "  • ai_user-action — user interactions (open browser/app, navigate to URL, tap, type, dismiss overlays); "
        "argument: action (natural language).",
        "  • ai_validation — checkpoints and assertions; argument: validation (natural language).",
        "  • ai_visual-comparison — visual/baseline comparison; argument: baselineId.",
        "Prefer ai_user-action for navigation (e.g. open browser and go to URL), not browser_goto / browser_open.",
        "Do not use browser_*, touch_tap, webpage.element_*, checkpoint_text, etc. unless the user explicitly "
        "requests a non-AI command or agreed that AI commands cannot meet a documented requirement.",
        "Structural helpers (add_logical_step, add_loop, add_condition, comment, wait) are OK; "
        "keep observable steps AI-driven when possible.",
        "Call get_command_definitions only for the AI command_ids you will use.",
        "cmd_arguments keys are the parameter names returned by get_command_definitions "
        "(mandatory_parameters / optional_parameters); undeclared names are rejected.",
        "Keep command arguments nested inside cmd_arguments: the 'action' parameter of ai_user-action "
        "collides with the tool's own action key if flattened into args.",
        "Values are constants by default; pass {\"data_source\": \"VARIABLE\", \"value\": \"<variable name>\"} "
        "to bind an argument to a script variable, or {\"data_source\": \"DATATABLE\", \"table_name\": \"<table>\", "
        "\"column\": \"<column>\"} to bind it to a DataTable column.",
        "modify_command merges: only the arguments sent are replaced, the others keep their current value.",
        "Values are validated against the declared type, range, allowed values and data sources; "
        "view_test_step reports all four for every argument of an existing step.",
    ]

def format_ai_scriptless_tests_filter_values(tests: dict[str, Any], params: Optional[dict] = None) -> dict[str, Any]:
    filter_values = {
        "test_name": [],
        "owner_list": [],
    }

    for item_visibility in tests["items"]:
        stack_tests = list(item_visibility.get("items", []))
        while stack_tests:
            test = stack_tests.pop()
            node_type = test["type"]
            if node_type == "SIMPLE":
                test_name = test['name'].rstrip('.xml')
                if test_name not in filter_values["test_name"]:
                    filter_values["test_name"].append(test_name)
                if test['createdBy'] not in filter_values["owner_list"]:
                    filter_values["owner_list"].append(test['createdBy'])
                if test['modifiedBy'] not in filter_values["owner_list"]:
                    filter_values["owner_list"].append(test['modifiedBy'])
            elif node_type == "CONTAINER":
                stack_tests.extend(reversed(test.get("items", [])))
    return filter_values


def format_ai_scriptless_tests(tests: dict[str, Any], params: Optional[dict] = None) -> List[dict[str, Any]]:
    formatted_ai_scriptless_tests = []
    filters = params.get("filters", {})
    page_size = params["page_size"]
    skip = params["skip"]
    offset = skip + page_size

    for item_visibility in tests["items"]:
        visibility = item_visibility["visibility"]
        if "visibility" in filters and visibility != filters.get("visibility"):
            continue
        stack_tests = list(item_visibility.get("items", []))
        while stack_tests:
            test = stack_tests.pop()
            node_type = test["type"]
            if node_type == "SIMPLE":
                if "test_name" in filters and filters["test_name"].lower() not in test["name"].lower():
                    continue
                if "owner_list" in filters and test['createdBy'] not in filters.get('owner_list', []):
                    continue
                test_formatted = f"id:{test['key']} name:{test['name'].rstrip('.xml')} created[user:{test['createdBy']} date:{test['creationTime']['formatted']}] modified[user:{test['modifiedBy']} date:{test['modificationTime']['formatted']}]"
                formatted_ai_scriptless_tests.append(test_formatted)
            elif node_type == "CONTAINER":
                stack_tests.extend(reversed(test.get("items", [])))

            if len(formatted_ai_scriptless_tests) > offset:
                break

    if len(formatted_ai_scriptless_tests) >= offset:
        offset = len(formatted_ai_scriptless_tests) - 1

    return formatted_ai_scriptless_tests[skip:offset]


def _command_id(command: Optional[str], subcommand: Optional[str]) -> Optional[str]:
    if not command:
        return None
    sub = subcommand or ""
    if sub:
        return f"{command}_{sub}".replace("/", "_")
    return command.replace("/", "_")


def _definitions_map(command_definitions: Optional[list]) -> dict[str, dict[str, Any]]:
    if not command_definitions:
        return {}
    return {item["commandId"]: item for item in command_definitions if "commandId" in item}


def _argument_value(element: dict[str, Any], argument_name: str) -> Optional[str]:
    for argument in element.get("arguments", []):
        if argument.get("name") == argument_name:
            data = argument.get("data", {})
            return data.get("value")
    return None


def _definition_display_name(command_id: Optional[str], definitions_map: dict[str, dict[str, Any]]) -> Optional[str]:
    if not command_id or command_id not in definitions_map:
        return None
    definition = definitions_map[command_id]
    display = definition.get("data", {}).get("display", {})
    return display.get("name") or definition.get("name")


def _definition_data(definition: dict[str, Any]) -> dict[str, Any]:
    data = definition.get("data", definition)
    return data if isinstance(data, dict) else {}


def _iter_definition_parameters(definition: dict[str, Any]):
    seen: set[str] = set()
    for key in ("parameters", "mandatoryParameters", "optionalParameters"):
        for param in _definition_data(definition).get(key) or []:
            if not isinstance(param, dict):
                continue
            param_name = param.get("name") or param.get("parameterName")
            if not param_name or param_name in seen:
                continue
            seen.add(param_name)
            yield param


def _should_include_parameter_in_step_display(param: dict[str, Any]) -> bool:
    display = param.get("display") or {}
    if display.get("editorLevel") != "PUBLIC":
        return False
    in_report = display.get("inReport", param.get("inReport"))
    return in_report is True


def _parameter_display_label(param: dict[str, Any]) -> str:
    display = param.get("display") or {}
    param_name = param.get("name") or param.get("parameterName") or ""
    return display.get("name") or param_name


def _format_argument_display_value(element: dict[str, Any], argument_name: str) -> Optional[str]:
    # A multivalued parameter has several arguments under one name; the UI shows the last.
    matches = [a for a in element.get("arguments", []) if a.get("name") == argument_name]
    if not matches:
        return None
    data = matches[-1].get("data", {})
    value = data.get("value")
    if value is None:
        return None
    if data.get("secured"):
        return "<secured>"
    return str(value)


def _command_step_display_name(
        element: dict[str, Any],
        command_id: Optional[str],
        definitions_map: dict[str, dict[str, Any]],
) -> Optional[str]:
    if not command_id or command_id not in definitions_map:
        return None

    base_name = _definition_display_name(command_id, definitions_map)
    if not base_name:
        return None

    segments: list[str] = []
    definition = definitions_map[command_id]
    for param in _iter_definition_parameters(definition):
        if not _should_include_parameter_in_step_display(param):
            continue
        param_name = param.get("name") or param.get("parameterName")
        if not param_name:
            continue
        value = _format_argument_display_value(element, param_name)
        if value is None or value == "":
            continue
        segments.append(f"{_parameter_display_label(param)}: {value}")

    if not segments:
        return base_name
    return f"{base_name} ({', '.join(segments)})"


def _ai_primary_step_display_name(
        element: dict[str, Any],
        command_id: Optional[str],
        definitions_map: dict[str, dict[str, Any]],
        argument_name: str,
) -> Optional[str]:
    primary_text = _argument_value(element, argument_name)
    if primary_text:
        return str(primary_text)
    return _definition_display_name(command_id, definitions_map)


def _step_display_name(element: dict[str, Any], definitions_map: dict[str, dict[str, Any]]) -> str:
    element_type = element.get("@type", "")
    command = element.get("command")
    subcommand = element.get("subcommand")
    command_id = _command_id(command, subcommand)

    if command == "ai" and subcommand == "user-action":
        display_name = _ai_primary_step_display_name(
            element, command_id, definitions_map, "action",
        )
        if display_name:
            return display_name

    if command == "ai" and subcommand == "validation":
        display_name = _ai_primary_step_display_name(
            element, command_id, definitions_map, "validation",
        )
        if display_name:
            return display_name

    if element_type == "Loop":
        iterator = element.get("iterator", {})
        variable = iterator.get("variable")
        if variable:
            return f"Loop ({variable})"
        count = iterator.get("count")
        if count is not None:
            # The API serializes the count as a float; 2.0 reads as a broken count.
            return f"Loop ({_range_bound(count)})"
        return "Loop"

    if element_type == "IfStatement":
        label = element.get("label")
        if label:
            return f"Condition ({label})"
        return "Condition"

    if element_type == "LogicalStep":
        # The UI stores the group title in `name`; `label` is only what older MCP writes used.
        label = element.get("name") or element.get("label")
        if label:
            return label
        return "Step"

    if element_type == "Branch":
        clause = element.get("clause", "")
        return clause.title() if clause else "Branch"

    display_name = _command_step_display_name(element, command_id, definitions_map)
    if not display_name:
        display_name = _definition_display_name(command_id, definitions_map)
    if display_name:
        return display_name

    if command:
        if subcommand:
            return f"{command}/{subcommand}"
        return command

    return element_type or "Unknown"


def _format_flow_element(
        element: dict[str, Any],
        definitions_map: dict[str, dict[str, Any]],
        step_path: str,
) -> ScriptFlowElement:
    element_type = element.get("@type", "")
    command = element.get("command")
    subcommand = element.get("subcommand")
    children: List[ScriptFlowElement] = []

    if element_type == "IfStatement":
        for branch_index, branch in enumerate(element.get("branches", [])):
            branch_path = f"{step_path}.b{branch_index}"
            branch_label = branch.get("clause", "Branch")
            branch_children = [
                _format_flow_element(child, definitions_map, f"{branch_path}.{child_index}")
                for child_index, child in enumerate(branch.get("flowElements", []))
            ]
            children.append(ScriptFlowElement(
                type="Branch",
                name=branch_label.title() if branch_label else "Branch",
                active=branch.get("active", True),
                step_path=branch_path,
                children=branch_children,
            ))
    else:
        for child_index, child in enumerate(element.get("flowElements", [])):
            children.append(
                _format_flow_element(child, definitions_map, f"{step_path}.{child_index}")
            )

    return ScriptFlowElement(
        type=element_type,
        name=_step_display_name(element, definitions_map),
        command=command,
        subcommand=subcommand,
        active=element.get("active", True),
        step_path=step_path,
        children=children,
    )


def _format_root_flow_elements(
        flow_elements: list[dict[str, Any]],
        definitions_map: dict[str, dict[str, Any]],
) -> List[ScriptFlowElement]:
    return [
        _format_flow_element(element, definitions_map, str(index))
        for index, element in enumerate(flow_elements)
    ]


def format_test_structure(payload: dict[str, Any], params: Optional[dict] = None) -> TestStructure:
    item_key = params.get("item_key", "") if params else ""
    script = copy.deepcopy(payload.get("script", {}))
    normalize_if_statement_aliases(script)
    definitions_map = _definitions_map(payload.get("commandDefinitions"))

    parameters = []
    for parameter in script.get("parameters", []):
        data = parameter.get("data", {})
        parameters.append(ScriptParameter(
            name=data.get("name", parameter.get("name", "")),
            type=data.get("@type", "Unknown"),
        ))

    flow_elements = _format_root_flow_elements(script.get("flowElements", []), definitions_map)

    info = script.get("info", {})
    return TestStructure(
        item_key=item_key,
        parameters=parameters,
        model_version=info.get("modelVersion"),
        flow_elements=flow_elements,
    )


def _restriction_allowed_values(
        param: dict[str, Any],
        command_id: Optional[str] = None,
) -> List[str]:
    return list(restriction_allowed_values(param, command_id))


def _renamed_declared_label(
        command_id: Optional[str],
        name: Optional[str],
        declared: Optional[str],
) -> Optional[str]:
    """The declared label, reported only where the editor shows a different one."""
    shown = parameter_label(command_id, name, declared)
    return declared if shown != declared else None


def _range_bound(value: Any) -> str:
    # The API serializes bounds as floats (0.0, 3600.0); render integral ones as integers.
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _restriction_range(param: dict[str, Any]) -> Optional[str]:
    minimum, maximum = restriction_range(param)
    if minimum is None and maximum is None:
        return None
    return f"{_range_bound(minimum)}..{_range_bound(maximum)}"


def _step_parameters_map(definition: Optional[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not definition:
        return {}
    mandatory_names = {
        param.get("name") or param.get("parameterName")
        for param in _definition_data(definition).get("mandatoryParameters") or []
        if isinstance(param, dict)
    }
    parameters: dict[str, dict[str, Any]] = {}
    for param in _iter_definition_parameters(definition):
        name = param.get("name") or param.get("parameterName")
        parameters[name] = {**param, "_mandatory": name in mandatory_names}
    return parameters


def _step_argument(
        argument: dict[str, Any],
        parameters: dict[str, dict[str, Any]],
        command_id: Optional[str] = None,
) -> ScriptStepArgument:
    name = argument.get("name", "")
    data = argument.get("data") or {}
    value = data.get("value")
    if data.get("secured") and value:
        value = "<secured>"
    param = parameters.get(name)
    display = (param or {}).get("display") or {}
    return ScriptStepArgument(
        name=name,
        value=value,
        data_source=data.get("dataSource"),
        parameter_type=(param or {}).get("dataType"),
        mandatory=(param or {}).get("_mandatory") if param else None,
        declared=param is not None or not parameters,
        allowed_data_sources=list((param or {}).get("dataSources") or []),
        allowed_values=_restriction_allowed_values(param or {}, command_id),
        value_range=_restriction_range(param or {}),
        label=parameter_label(command_id, name, display.get("name")),
        declared_label=_renamed_declared_label(command_id, name, display.get("name")),
        table_name=data.get("tableName"),
        column=data.get("column"),
    )


def _step_argument_is_set(argument: ScriptStepArgument) -> bool:
    """A DataTable binding is a value even though it carries no value field."""
    if argument.data_source == "DATATABLE":
        return bool(argument.table_name or argument.column)
    return argument.value is not None and str(argument.value).strip() != ""


def _unset_step_parameters(
        element: dict[str, Any],
        parameters: dict[str, dict[str, Any]],
        command_id: Optional[str] = None,
) -> List[ScriptStepParameter]:
    set_names = {argument.get("name") for argument in element.get("arguments", [])}
    unset: List[ScriptStepParameter] = []
    for name, param in parameters.items():
        if name in set_names:
            continue
        display = param.get("display") or {}
        mandatory = bool(param.get("_mandatory"))
        unset.append(ScriptStepParameter(
            name=name,
            parameter_type=param.get("dataType"),
            mandatory=mandatory,
            default_value=param.get("defaultValue"),
            allowed_data_sources=list(param.get("dataSources") or []),
            allowed_values=_restriction_allowed_values(param, command_id),
            value_range=_restriction_range(param),
            label=parameter_label(command_id, name, display.get("name")),
            declared_label=_renamed_declared_label(command_id, name, display.get("name")),
            # Some commands declare ~60 optional parameters with long help texts; carrying them
            # all would dwarf the step itself. Names, types and accepted values are enough to
            # edit, and get_command_definitions has the full help when it is actually needed.
            help_text=(param.get("helpText") or display.get("helpText")) if mandatory else None,
        ))
    unset.sort(key=lambda parameter: (not parameter.mandatory, parameter.name))
    return unset


def _step_children_paths(element: dict[str, Any], step_path: str) -> List[str]:
    if element.get("@type") == "IfStatement":
        return [
            f"{step_path}.b{branch_index}"
            for branch_index, _branch in enumerate(element.get("branches", []))
        ]
    return [
        f"{step_path}.{child_index}"
        for child_index, _child in enumerate(element.get("flowElements", []))
    ]


def _step_detail_notes(element: dict[str, Any], detail_arguments: List[ScriptStepArgument]) -> List[str]:
    notes: List[str] = []
    undeclared = [argument.name for argument in detail_arguments if not argument.declared]
    if undeclared:
        notes.append(
            f"Argument(s) not declared by the command: {', '.join(undeclared)}. "
            "Perfecto ignores them at execution time; they were most likely persisted by mistake."
        )
    if detail_arguments:
        notes.append(
            "To edit, call modify_command with cmd_arguments keyed by these argument names. "
            "Only the arguments you send change; the others keep their current value."
        )
    if element.get("active") is False:
        notes.append("This step is excluded from the run; re-include it with set_command_enabled.")
    empty_mandatory = [
        argument.name for argument in detail_arguments
        if argument.mandatory and not _step_argument_is_set(argument)
    ]
    if empty_mandatory:
        notes.append(
            f"Mandatory argument(s) with no value: {', '.join(empty_mandatory)}. "
            "The step will not do anything until they are set with modify_command."
        )
    return notes


def format_step_detail(
        element: dict[str, Any],
        item_key: str,
        step_path: str,
        command_definitions: Optional[list] = None,
        statement_step_path: Optional[str] = None,
) -> ScriptStepDetail:
    """Full configuration of one step, joined with what its command declares."""
    definitions_map = _definitions_map(command_definitions)
    command_id = _command_id(element.get("command"), element.get("subcommand"))
    parameters = _step_parameters_map(definitions_map.get(command_id) if command_id else None)
    arguments = [
        _step_argument(argument, parameters, command_id)
        for argument in element.get("arguments", [])
    ]
    iterator = element.get("iterator") or {}
    return ScriptStepDetail(
        item_key=item_key,
        step_path=step_path,
        type=element.get("@type", ""),
        name=_step_display_name(element, definitions_map),
        command_id=command_id,
        command=element.get("command"),
        subcommand=element.get("subcommand"),
        active=element.get("active", True),
        error_policy=element.get("errorPolicy"),
        comment=element.get("comment"),
        arguments=arguments,
        unset_parameters=_unset_step_parameters(element, parameters, command_id),
        label=element.get("name") or element.get("label"),
        statement_step_path=statement_step_path,
        loop_count=iterator.get("count"),
        loop_variable=iterator.get("variable"),
        children=_step_children_paths(element, step_path),
        notes=_step_detail_notes(element, arguments),
    )


def _flatten_command_catalog(node: dict[str, Any], category: Optional[str] = None) -> List[CommandCatalogEntry]:
    entries: List[CommandCatalogEntry] = []
    node_name = node.get("name")
    node_category = node_name if node.get("children") is not None else category

    if "commandId" in node:
        entries.append(CommandCatalogEntry(
            command_id=node["commandId"],
            name=node.get("name", node["commandId"]),
            path=node.get("path", ""),
            status=node.get("status"),
            category=category,
        ))

    for child in node.get("children", []):
        entries.extend(_flatten_command_catalog(child, node_category))

    return entries


def format_command_catalog(catalog: dict[str, Any], params: Optional[dict] = None) -> List[CommandCatalogEntry]:
    return _flatten_command_catalog(catalog)


def _parameter_names(parameters: Optional[list]) -> List[str]:
    if not parameters:
        return []
    return [param.get("name", param.get("parameterName", "")) for param in parameters if param.get("name") or param.get("parameterName")]


def _variable_type_label(data: dict[str, Any]) -> str:
    data_type = data.get("@type", "Unknown")
    if data_type == "StringData":
        return "secured_string" if data.get("secured") else "string"
    mapping = {
        "BooleanData": "boolean",
        "IntegerData": "number",
        "HandsetData": "device",
        "MediaData": "media",
        "TableData": "datatable",
    }
    return mapping.get(data_type, data_type)


def format_test_variables(variables: Any, params: Optional[dict] = None) -> List[ScriptVariableSummary]:
    if not isinstance(variables, list):
        return []

    formatted: List[ScriptVariableSummary] = []
    for variable in variables:
        if not isinstance(variable, dict):
            continue
        data = variable.get("data", {})
        value = data.get("value")
        if data.get("secured") and value:
            value = "<secured>"
        formatted.append(ScriptVariableSummary(
            name=data.get("name", ""),
            type=_variable_type_label(data),
            value=value,
            secured=bool(data.get("secured")),
            set_at_runtime=variable.get("@type") == "Parameter",
        ))
    return formatted


def format_snapshots_list(response: Any, params: Optional[dict] = None) -> SnapshotListResult:
    snapshots = response.get("snapshots", []) if isinstance(response, dict) else response
    if not isinstance(snapshots, list):
        snapshots = []

    formatted: List[SnapshotSummary] = []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        key = snapshot.get("key", "")
        creation = snapshot.get("creationTime") or snapshot.get("createdTime") or {}
        created_time = creation.get("formatted") if isinstance(creation, dict) else creation
        formatted.append(SnapshotSummary(
            key=key,
            version=snapshot.get("version"),
            comment=snapshot.get("comment"),
            created_by=snapshot.get("createdBy"),
            created_time=created_time,
            is_current=key == "<current>",
        ))

    formatted.sort(key=lambda entry: (0 if entry.is_current else 1, entry.key))

    test_id = params.get("test_id") if params else None
    return SnapshotListResult(
        test_id=test_id,
        count=len(formatted),
        snapshots=formatted,
        notes=[
            "Every POST script save (including save_test without comment) adds a new UUID entry to snapshot history.",
            "The '<current>' entry marks the live editable script; use view_test_structure with test_id for its structure.",
            "Open historical versions with view_snapshot using a UUID key from this list, not '<current>'.",
            "The comment argument on save_test/save_test_as labels '<current>' (UI: Save with comment); it does not skip version creation.",
        ],
    )


def format_command_definitions(response: Any, params: Optional[dict] = None) -> List[CommandDefinitionSummary]:
    definitions = response if isinstance(response, list) else response.get("definitions", response.get("items", []))
    if not isinstance(definitions, list):
        definitions = [definitions] if definitions else []

    summaries: List[CommandDefinitionSummary] = []
    for definition in definitions:
        if not isinstance(definition, dict):
            continue
        command_id = definition.get("commandId", "")
        data = definition.get("data", definition)
        display = data.get("display", {})
        summaries.append(CommandDefinitionSummary(
            command_id=command_id,
            name=display.get("name") or definition.get("name") or command_id,
            mandatory_parameters=_parameter_names(data.get("mandatoryParameters")),
            optional_parameters=_parameter_names(data.get("optionalParameters")),
            help_text=display.get("helpText") or data.get("helpText"),
            raw=definition,
        ))
    return summaries
