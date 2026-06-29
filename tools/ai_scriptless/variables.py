from typing import Any, Optional


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
