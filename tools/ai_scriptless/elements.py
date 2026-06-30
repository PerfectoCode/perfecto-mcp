from typing import Any, Optional

from tools.ai_scriptless.commands import (
    command_id_from_element,
    get_command_spec,
    parse_command_id,
)


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


def build_arguments(command_id: str, arguments: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    spec = get_command_spec(command_id)
    merged = spec.default_arguments_merged()
    if arguments:
        for name, value in spec.normalize_argument_names(arguments).items():
            if isinstance(value, dict) and "data_source" in value:
                merged[name] = (value["data_source"], value.get("value"))
            else:
                merged[name] = ("CONSTANT", value)
    spec.drop_superseded_aliases(merged)
    return [_make_argument(name, value, source) for name, (source, value) in merged.items()]


def build_flow_element(command_id: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    command, subcommand = parse_command_id(command_id)
    spec = get_command_spec(command_id)
    return {
        "@type": spec.element_type,
        "validations": [],
        "errorPolicy": spec.error_policy,
        "command": command,
        "subcommand": subcommand,
        "arguments": build_arguments(command_id, arguments),
        "comment": None,
        "status": None,
        "active": True,
    }


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
    }


def build_logical_step(label: Optional[str] = None) -> dict[str, Any]:
    return {
        "@type": "LogicalStep",
        "flowElements": [],
        "active": True,
        "label": label or "",
        "comment": None,
        "status": None,
    }


def build_loop(count: int = 1) -> dict[str, Any]:
    return {
        "@type": "Loop",
        "iterator": {"@type": "RepeatIterator", "count": count},
        "flowElements": [],
        "active": True,
        "comment": None,
        "status": None,
    }


def build_if_statement(expression: Optional[str] = None, label: Optional[str] = None) -> dict[str, Any]:
    then_branch = build_branch("THEN")
    else_branch = build_branch("ELSE")
    statement: dict[str, Any] = {
        "@type": "IfStatement",
        "branches": [then_branch, else_branch],
        # thenClause/elseClause must alias branches[0]/[1] — tree navigation and API layout share the same Branch objects.
        "thenClause": then_branch,
        "elseClause": else_branch,
        "label": label or "",
        "numOfFlowElements": 3,
        "comment": None,
        "status": None,
        "active": True,
    }
    if expression:
        statement["expression"] = expression
    return statement


def new_empty_script() -> dict[str, Any]:
    return {
        "@type": "Script",
        "parameters": [{
            "@type": "Parameter",
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


def normalize_if_statement_aliases(script: dict[str, Any]) -> None:
    """Re-alias thenClause/elseClause to branches[0]/[1] after API load.

    Perfecto returns duplicate Branch trees; tree navigation edits branches[] only.
    On save, the API canonicalizes from branches[] (thenClause is reconciled on read).
    When counts match but content differs, branches[] wins — same rule as sync_branch_children.
    If only thenClause has children and branches[0] is empty, copy clause children first
    or Perfecto will drop them on persist.
    """

    def sync_branch_children(branch: dict[str, Any], clause: Optional[dict[str, Any]]) -> None:
        if clause is None or clause is branch:
            return
        branch_children = branch.get("flowElements", [])
        clause_children = clause.get("flowElements", [])
        if not branch_children and clause_children:
            branch["flowElements"] = clause_children
        elif branch_children and clause_children and branch_children is not clause_children:
            if len(clause_children) > len(branch_children):
                branch["flowElements"] = clause_children

    def walk(flow_elements: list[dict[str, Any]]) -> None:
        for element in flow_elements:
            element_type = element.get("@type")
            if element_type in ("LogicalStep", "Loop"):
                walk(element.get("flowElements", []))
            elif element_type == "IfStatement":
                branches = element.get("branches", [])
                if len(branches) >= 2:
                    sync_branch_children(branches[0], element.get("thenClause"))
                    sync_branch_children(branches[1], element.get("elseClause"))
                    element["thenClause"] = branches[0]
                    element["elseClause"] = branches[1]
                for branch in branches:
                    walk(branch.get("flowElements", []))

    walk(script.get("flowElements", []))


def strip_non_api_script_fields(script: dict[str, Any]) -> None:
    def walk_element(element: dict[str, Any]) -> None:
        element.pop("uuid", None)
        for child in element.get("flowElements", []):
            walk_element(child)
        if element.get("@type") == "IfStatement":
            for branch in element.get("branches", []):
                walk_element(branch)
            for clause_key in ("thenClause", "elseClause"):
                clause = element.get(clause_key)
                if clause:
                    walk_element(clause)

    for element in script.get("flowElements", []):
        walk_element(element)


def update_element_arguments(element: dict[str, Any], arguments: dict[str, Any]) -> None:
    command_id = command_id_from_element(element)
    spec = get_command_spec(command_id)
    existing = {argument["name"]: argument for argument in element.get("arguments", [])}
    for name, value in spec.normalize_argument_names(arguments).items():
        if isinstance(value, dict) and "data_source" in value:
            source = value["data_source"]
            argument_value = value.get("value")
        else:
            source = "CONSTANT"
            argument_value = value
        existing[name] = _make_argument(name, argument_value, source)
    spec.drop_superseded_aliases(existing)
    element["arguments"] = list(existing.values())
