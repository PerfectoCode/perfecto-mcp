from typing import TYPE_CHECKING, Any, Optional

from tools.ai_scriptless.commands import (
    command_id_from_element,
    get_command_spec,
    parse_command_id,
)

if TYPE_CHECKING:  # type-only: definitions reaches the API, elements must stay pure
    from tools.ai_scriptless.definitions import CommandContract


def _make_argument(name: str, value: Any, data_source: str = "CONSTANT") -> dict[str, Any]:
    if data_source == "VARIABLE":
        data: dict[str, Any] = {
            "@type": "VariableArgumentData",
            "dataSource": "VARIABLE",
            "value": value,
        }
    elif data_source == "DATATABLE":
        # A DataTable binding carries tableName/column instead of a value.
        binding = value if isinstance(value, dict) else {}
        data = {
            "@type": "DataTableArgumentData",
            "dataSource": "DATATABLE",
            "tableName": binding.get("tableName"),
            "column": binding.get("column"),
        }
    else:
        data = {
            "@type": "ConstantArgumentData",
            "dataSource": "CONSTANT",
            "secured": False,
            "value": value,
        }
    return {"@type": "FunctionArgument", "name": name, "data": data}


def _coerce(name: str, value: Any, contract: Optional["CommandContract"]) -> Any:
    """Normalize a constant to the declared type; a no-op without a contract."""
    if contract is None:
        return value
    # Local import: definitions reaches the API, elements must stay importable without it.
    from tools.ai_scriptless.definitions import coerce_argument_value

    return coerce_argument_value(value, contract.parameter(name))


def _argument_payload(value: dict[str, Any]) -> Any:
    """What travels with the data source: a DataTable binding, or a plain value."""
    if str(value.get("data_source") or "").upper() == "DATATABLE":
        return {
            "tableName": value.get("table_name", value.get("tableName")),
            "column": value.get("column"),
        }
    return value.get("value")


def _argument_occurrences(
        name: str,
        value: Any,
        contract: Optional["CommandContract"],
) -> list[tuple[str, Any]]:
    """(data source, payload) per occurrence.

    A list means a multivalued parameter: Perfecto persists one FunctionArgument per
    occurrence, all sharing the parameter name, in order.
    """
    values = value if isinstance(value, list) else [value]
    occurrences: list[tuple[str, Any]] = []
    for item in values:
        if isinstance(item, dict) and "data_source" in item:
            occurrences.append((item["data_source"], _argument_payload(item)))
        else:
            occurrences.append(("CONSTANT", _coerce(name, item, contract)))
    return occurrences


def build_arguments(
        command_id: str,
        arguments: Optional[dict[str, Any]],
        contract: Optional["CommandContract"] = None,
) -> list[dict[str, Any]]:
    spec = get_command_spec(command_id)
    declared = contract.declared_names if contract else frozenset()
    merged: dict[str, list[tuple[str, Any]]] = {
        name: [(source, value)]
        for name, (source, value) in spec.default_arguments_merged().items()
        # The fallback spec seeds handsetId for every unregistered command; keep a default
        # only when the command actually declares that parameter.
        if not declared or name in declared
    }
    if arguments:
        for name, value in spec.normalize_argument_names(arguments).items():
            merged[name] = _argument_occurrences(name, value, contract)
    spec.drop_superseded_aliases(merged)
    return [
        _make_argument(name, value, source)
        for name, occurrences in merged.items()
        for source, value in occurrences
    ]


def build_flow_element(
        command_id: str,
        arguments: Optional[dict[str, Any]] = None,
        contract: Optional["CommandContract"] = None,
) -> dict[str, Any]:
    """Build a flow element, preferring the declared contract over the local spec.

    element_type and errorPolicy decide whether a failing step aborts the test or is
    only reported, so the repository declaration wins whenever it is available.
    """
    command, subcommand = parse_command_id(command_id)
    spec = get_command_spec(command_id)
    element_type = (contract.element_type if contract else None) or spec.element_type
    error_policy = (contract.error_policy if contract else None) or spec.error_policy
    element = {
        "@type": element_type,
        "errorPolicy": error_policy,
        "command": command,
        "subcommand": subcommand,
        "arguments": build_arguments(command_id, arguments, contract),
        "comment": None,
        "status": None,
        "active": True,
    }
    if element_type != "Validation":
        # The UI writes validations[] on Action steps only; Validation steps omit it.
        element["validations"] = []
    return element


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
    # The group's title lives in `name` (the UI's "Name" parameter), not in `label`.
    return {
        "@type": "LogicalStep",
        "flowElements": [],
        "active": True,
        "name": label or "",
        "transaction": "",
        "comment": None,
        "status": None,
    }


def build_loop(count: int = 1, variable: Optional[str] = None) -> dict[str, Any]:
    """A loop repeats a fixed number of times, or as many times as a number variable says."""
    iterator = (
        {"@type": "VariableIterator", "variable": variable} if variable
        else {"@type": "RepeatIterator", "count": count}
    )
    return {
        "@type": "Loop",
        "iterator": iterator,
        "flowElements": [],
        "active": True,
        "comment": None,
        "status": None,
    }


def build_if_statement(label: Optional[str] = None) -> dict[str, Any]:
    """Build a condition.

    A condition carries no expression: the branch taken depends on the result of the
    preceding step, which the UI shows as the condition's "Statement" and marks with
    errorPolicy CATCH. An `expression` field is dropped by the API.
    """
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


def update_element_arguments(
        element: dict[str, Any],
        arguments: dict[str, Any],
        contract: Optional["CommandContract"] = None,
) -> None:
    command_id = command_id_from_element(element)
    spec = get_command_spec(command_id)

    # Keyed by name but keeping every occurrence: a multivalued parameter has several
    # arguments under the same name, and collapsing them would drop all but the last.
    existing: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for argument in element.get("arguments", []):
        name = argument.get("name", "")
        if name not in existing:
            existing[name] = []
            order.append(name)
        existing[name].append(argument)

    for name, value in spec.normalize_argument_names(arguments).items():
        # Sending a parameter replaces its whole list, the way the UI's row editor does.
        existing[name] = [
            _make_argument(name, argument_value, source)
            for source, argument_value in _argument_occurrences(name, value, contract)
        ]
        if name not in order:
            order.append(name)

    spec.drop_superseded_aliases(existing)
    element["arguments"] = [
        argument for name in order if name in existing for argument in existing[name]
    ]
