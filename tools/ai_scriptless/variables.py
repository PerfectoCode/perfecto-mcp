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
        # A boolean has three states in the UI: Null, True and False.
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return value
        normalized = str(value).lower()
        if normalized == "null":
            return None
        if normalized not in ("true", "false"):
            raise ValueError("boolean value must be true, false or null")
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


# Where a declaration lives depends on "Set at runtime" (the UI checkbox):
# checked -> parameters[] as a Parameter (DUT is one), unchecked -> variables[] as a Variable.
# The UI's "Configure test variables" dialog lists both, parameters first.
VARIABLE_ARRAYS = ("parameters", "variables")

DUT_NAME = "DUT"


def variable_array_for(set_at_runtime: bool) -> str:
    return "parameters" if set_at_runtime else "variables"


def locate_variable(
        script: dict[str, Any],
        variable_name: str,
) -> Optional[tuple[str, int, dict[str, Any]]]:
    """Find a declaration in either array: (array key, index, entry)."""
    for array_key in VARIABLE_ARRAYS:
        for index, variable in enumerate(script.get(array_key) or []):
            if not isinstance(variable, dict):
                continue
            if variable.get("data", {}).get("name") == variable_name:
                return array_key, index, variable
    return None


def find_variable(script: dict[str, Any], variable_name: str) -> Optional[tuple[int, dict[str, Any]]]:
    located = locate_variable(script, variable_name)
    if located is None:
        return None
    _array_key, index, variable = located
    return index, variable


def list_script_variables(script: dict[str, Any]) -> list[dict[str, Any]]:
    """Every declaration, runtime parameters first, as the UI dialog lists them."""
    entries: list[dict[str, Any]] = []
    for array_key in VARIABLE_ARRAYS:
        entries.extend(
            variable for variable in (script.get(array_key) or []) if isinstance(variable, dict)
        )
    return entries


def add_script_variable(
        script: dict[str, Any],
        name: str,
        variable_type: str,
        value: Any,
        set_at_runtime: bool = False,
) -> dict[str, Any]:
    validate_variable_name(name)
    if name == DUT_NAME:
        raise ValueError("DUT is a test parameter, not a script variable")
    if locate_variable(script, name):
        raise ValueError(f"variable already exists: {name}")
    entry = build_variable_entry(name, variable_type, value, set_at_runtime)
    script.setdefault(variable_array_for(set_at_runtime), []).append(entry)
    return entry


def modify_script_variable(
        script: dict[str, Any],
        variable_name: str,
        value: Optional[Any] = None,
        variable_type: Optional[str] = None,
        set_at_runtime: Optional[bool] = None,
) -> dict[str, Any]:
    located = locate_variable(script, variable_name)
    if located is None:
        raise ValueError(f"variable not found: {variable_name}")
    array_key, index, variable = located
    if variable_name == DUT_NAME:
        raise ValueError(
            "DUT is the device parameter execute_test fills in; it cannot be modified here"
        )
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
        # Toggling "Set at runtime" moves the declaration to the other array.
        target_array = variable_array_for(set_at_runtime)
        if target_array != array_key:
            script.get(array_key, []).pop(index)
            script.setdefault(target_array, []).append(variable)
    return variable


def delete_script_variable(script: dict[str, Any], variable_name: str) -> None:
    located = locate_variable(script, variable_name)
    if located is None:
        raise ValueError(f"variable not found: {variable_name}")
    array_key, index, _variable = located
    if variable_name == DUT_NAME:
        raise ValueError(
            "DUT is the device parameter every step binds handsetId to; deleting it breaks the test"
        )
    script.get(array_key, []).pop(index)


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


# Parameter dataType (command repository) -> variable data @type (script model).
# The UI only offers variables whose type matches the parameter being bound.
VARIABLE_DATA_TYPES_BY_PARAMETER_TYPE = {
    "STRING": frozenset({"StringData"}),
    "INTEGER": frozenset({"IntegerData"}),
    "NUMBER": frozenset({"IntegerData"}),
    "BOOLEAN": frozenset({"BooleanData"}),
    "HANDSET": frozenset({"HandsetData"}),
    "MEDIA": frozenset({"MediaData"}),
    "TABLE": frozenset({"TableData"}),
}


def variable_type_label(data: dict[str, Any]) -> str:
    """Our vocabulary for a variable's data type (string, number, device, ...)."""
    return _variable_type_from_data(data)


def bindable_values(script: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Everything an argument can bind to, by name.

    Script variables plus the test parameters (DUT lives in parameters[], not
    variables[]), which is how the UI lists them together.
    """
    bindable: dict[str, dict[str, Any]] = {}
    for entry in list(script.get("parameters", [])) + list(script.get("variables", [])):
        data = entry.get("data", {}) if isinstance(entry, dict) else {}
        name = data.get("name")
        if name:
            bindable[name] = data
    return bindable


def describe_bindable_values(script: dict[str, Any]) -> str:
    described = [
        f"{name} ({variable_type_label(data)})"
        for name, data in sorted(bindable_values(script).items())
    ]
    return ", ".join(described) if described else "none"
