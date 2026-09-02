"""Command contracts from the command repository API.

The repository declares what a command is (``data.type``, ``data.errorPolicy``)
and what it takes (``mandatoryParameters`` / ``optionalParameters``); the script
persists a flow element with an ``@type`` and a list of ``FunctionArgument``
entries whose names are those same parameter names. Parameter is the
declaration, argument is the assigned value.

Reading the contract instead of inferring it keeps two things honest:
- element type and error policy, which decide whether a failing step aborts the
  test (Action/ABORT) or is only reported (Validation/IGNORE);
- argument names, which Perfecto silently ignores when undeclared, so a typo
  only shows up as a step that does nothing at execution time.

Everything fails open on purpose: when the definitions API is unreachable or
does not declare something, authoring keeps working with the local defaults
rather than becoming unavailable.
"""

import asyncio
import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any, Optional

from config import perfecto
from config.token import PerfectoToken
from tools.ai_scriptless.commands import get_command_spec
from tools.utils import api_request

# data.type -> flow element @type in the script model.
ELEMENT_TYPE_BY_DEFINITION_TYPE = {
    "ACTION": "Action",
    "VALIDATION": "Validation",
}

# The five policies the legacy IDE documents (and the UI's "On-fail Result" offers):
# IGNORE reports the failure and goes on, ABORT ends the run, BREAK and CONTINUE act on the
# enclosing loop (abort outside one), CATCH feeds the result to a following condition.
SUPPORTED_ERROR_POLICIES = frozenset({"ABORT", "IGNORE", "BREAK", "CONTINUE", "CATCH"})


INTEGER_DATA_TYPES = frozenset({"INTEGER", "NUMBER"})
BOOLEAN_TRUE = frozenset({"true", "1", "yes"})
BOOLEAN_FALSE = frozenset({"false", "0", "no"})

# Enumerations whose persisted values are not exactly the declared restriction.value.
#
# For every dropdown-style enumeration the UI persists the declared value: setting
# checkpoint_text's "Match mode" to the label "Start with" stores ``startwith``.
# ai_visual-comparison's "Fail criteria" is the exception. It is edited through a
# multi-select dialog whose option list is hardcoded in the UI, and that list has
# drifted from the declaration in two places: the declared ``pixel_difference`` is
# stored as ``pixelDifference``, and ``moved`` is offered but declared nowhere. A
# value stored in the declared spelling is counted by the editor ("1 selected") but
# shows no ticked box, so it cannot be edited in the UI.
#
# Harvested by ticking every option in the editor, saving, and reading the persisted
# arguments back -- not from the script tree, which renders restriction.label rather
# than the stored value.
UI_PERSISTED_ENUM_VALUES: dict[tuple[str, str], tuple[str, ...]] = {
    ("ai_visual-comparison", "failCriteria"): (
        "device", "style", "value", "missing", "moved",
        "addition", "error", "uncategorized", "pixelDifference",
    ),
}


# Parameters the editor labels differently from their declared display.name.
#
# The declaration is not wrong about the parameter, only about what the user reads: typing into
# the field labelled "Prompt" stores `action`, verified by matching the editor's row (whose
# data-aid carries the parameter name) against the definition. Reporting the declared label
# would name a field nobody can find on screen, so the editor's wins and the declared one is
# reported alongside it.
UI_PARAMETER_LABELS: dict[tuple[str, str], str] = {
    ("ai_user-action", "action"): "Prompt",
}


def parameter_label(
        command_id: Optional[str],
        name: Optional[str],
        declared_label: Optional[str],
) -> Optional[str]:
    """The label the editor shows for this parameter, falling back to the declared one."""
    return UI_PARAMETER_LABELS.get((command_id or "", name or ""), declared_label)


def _enum_key(value: str) -> str:
    """Punctuation- and case-insensitive key, so ``pixel_difference`` matches ``pixelDifference``."""
    return re.sub(r"[^0-9a-z]+", "", str(value).casefold())


def restriction_allowed_values(
        param: dict[str, Any],
        command_id: Optional[str] = None,
) -> tuple[str, ...]:
    """Persisted values of an ENUMERATION/COMBO parameter, in declared order.

    Reports the spelling Perfecto stores, which for the parameters listed in
    UI_PERSISTED_ENUM_VALUES is the UI's display string rather than the declared one.
    """
    restriction = param.get("restriction") or {}
    if str(restriction.get("type") or "").upper() not in ("ENUMERATION", "COMBO"):
        return ()
    name = param.get("name") or param.get("parameterName") or ""
    persisted = UI_PERSISTED_ENUM_VALUES.get((command_id or "", name))
    if persisted:
        return persisted
    raw_values = restriction.get("value") or restriction.get("label") or ""
    candidates = raw_values if isinstance(raw_values, list) else str(raw_values).split(",")
    return tuple(str(value).strip() for value in candidates if str(value).strip())


def restriction_range(param: dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    """Numeric bounds of a RANGE parameter, or (None, None) when unrestricted."""
    restriction = param.get("restriction") or {}
    if str(restriction.get("type") or "").upper() != "RANGE":
        return None, None
    value_range = restriction.get("range") or {}
    return value_range.get("minValue"), value_range.get("maxValue")


@dataclass(frozen=True)
class ParameterContract:
    """What the repository declares for one parameter of one command."""

    name: str
    data_type: Optional[str] = None
    data_sources: frozenset[str] = frozenset()
    mandatory: bool = False
    default_value: Any = None
    allowed_values: tuple[str, ...] = ()
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    min_occurrences: int = 1
    max_occurrences: int = 1

    @property
    def is_multivalued(self) -> bool:
        """True when the parameter takes a list: the UI edits it as ordered rows."""
        return self.max_occurrences > 1

    @property
    def is_integer(self) -> bool:
        return (self.data_type or "").upper() in INTEGER_DATA_TYPES

    @property
    def is_boolean(self) -> bool:
        return (self.data_type or "").upper() == "BOOLEAN"

    def match_allowed_value(self, value: str) -> Optional[str]:
        """The persisted spelling of value, or None when it is not accepted.

        Falls back to a punctuation-insensitive comparison, which is what lets the declared
        ``pixel_difference`` (and the label ``Pixel difference``) resolve to the
        ``pixelDifference`` the UI stores. No declared enumeration relies on punctuation
        alone to tell two of its own values apart.
        """
        for allowed in self.allowed_values:
            if allowed.casefold() == value.casefold():
                return allowed
        key = _enum_key(value)
        for allowed in self.allowed_values:
            if _enum_key(allowed) == key:
                return allowed
        return None


@dataclass(frozen=True)
class CommandContract:
    """What the repository declares for one command. Fields are None when undeclared."""

    command_id: str
    mandatory: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()
    element_type: Optional[str] = None
    error_policy: Optional[str] = None
    parameters: dict[str, ParameterContract] = field(default_factory=dict)

    @property
    def declared_names(self) -> frozenset[str]:
        return self.mandatory | self.optional

    def parameter(self, name: str) -> Optional[ParameterContract]:
        return self.parameters.get(name)


_command_contract_cache: dict[tuple[str, str], Optional[CommandContract]] = {}
_cache_guard = asyncio.Lock()


def reset_command_contract_cache() -> None:
    """Drop memoized contracts (used by tests and after a cloud switch)."""
    _command_contract_cache.clear()


def _parse_parameter_contract(
        param: dict[str, Any],
        mandatory: bool,
        command_id: str = "",
) -> ParameterContract:
    minimum, maximum = restriction_range(param)
    return ParameterContract(
        name=param.get("name") or param.get("parameterName") or "",
        data_type=param.get("dataType"),
        data_sources=frozenset(str(source).upper() for source in (param.get("dataSources") or [])),
        mandatory=mandatory,
        default_value=param.get("defaultValue"),
        allowed_values=restriction_allowed_values(param, command_id),
        minimum=minimum,
        maximum=maximum,
        min_occurrences=int(param.get("minOccurrences") or 1),
        max_occurrences=int(param.get("maxOccurrences") or 1),
    )


def _parse_command_contract(command_id: str, definition: dict[str, Any]) -> CommandContract:
    data = definition.get("data", definition) if isinstance(definition, dict) else {}
    element_type = ELEMENT_TYPE_BY_DEFINITION_TYPE.get(str(data.get("type") or "").upper())
    error_policy = str(data.get("errorPolicy") or "").upper() or None
    if error_policy not in SUPPORTED_ERROR_POLICIES:
        # wait, for one, declares errorPolicy null: leave it to the local default.
        error_policy = None

    parameters: dict[str, ParameterContract] = {}
    for bucket, mandatory in (("mandatoryParameters", True), ("optionalParameters", False)):
        for param in data.get(bucket) or []:
            if not isinstance(param, dict):
                continue
            contract = _parse_parameter_contract(param, mandatory, command_id)
            if contract.name:
                parameters[contract.name] = contract

    return CommandContract(
        command_id=command_id,
        element_type=element_type,
        error_policy=error_policy,
        parameters=parameters,
    )


async def _fetch_command_contract(
        token: PerfectoToken,
        command_id: str,
) -> Optional[CommandContract]:
    # Local import: formatters.ai_scriptless imports tools.ai_scriptless.elements.
    from formatters.ai_scriptless import format_command_definitions

    definitions_url = perfecto.get_ai_scriptless_command_repository_url(token.cloud_name)
    definitions_url = definitions_url + "/commands/definitions"
    try:
        result = await api_request(
            token,
            "POST",
            endpoint=definitions_url,
            json={"commandIds": [command_id]},
            result_formatter=format_command_definitions,
        )
    except Exception:  # noqa: BLE001 - never block authoring on a definitions failure
        return None
    if result.error or not isinstance(result.result, list):
        return None
    for definition in result.result:
        if definition.command_id != command_id:
            continue
        contract = _parse_command_contract(command_id, definition.raw or {})
        return CommandContract(
            command_id=command_id,
            mandatory=frozenset(definition.mandatory_parameters),
            optional=frozenset(definition.optional_parameters),
            element_type=contract.element_type,
            error_policy=contract.error_policy,
            parameters=contract.parameters,
        )
    return None


async def command_contract(
        token: Optional[PerfectoToken],
        command_id: str,
) -> Optional[CommandContract]:
    """Contract declared for command_id, or None when unavailable."""
    if not token or not command_id:
        return None
    cache_key = (token.cloud_name, command_id)
    async with _cache_guard:
        if cache_key in _command_contract_cache:
            return _command_contract_cache[cache_key]
    contract = await _fetch_command_contract(token, command_id)
    async with _cache_guard:
        _command_contract_cache[cache_key] = contract
    return contract


def _accepted_names(command_id: str, name: str) -> set[str]:
    """The name plus its known aliases; the repository may declare any of them."""
    spec = get_command_spec(command_id)
    names = {name, spec.argument_aliases.get(name, name)}
    names |= {alias for alias, canonical in spec.argument_aliases.items() if canonical == name}
    return names


def _argument_value(value: Any) -> Any:
    if isinstance(value, dict) and "data_source" in value:
        if str(value.get("data_source") or "").upper() == "DATATABLE":
            # A DataTable binding has no value field; the table/column pair is the value.
            return value.get("table_name") or value.get("tableName") or value.get("column")
        return value.get("value")
    return value


def validate_argument_names(
        command_id: str,
        cmd_arguments: Optional[dict[str, Any]],
        contract: Optional[CommandContract],
) -> Optional[str]:
    """Error message when cmd_arguments carries names the command does not declare."""
    if not cmd_arguments or not contract or not contract.declared_names:
        return None
    known = contract.declared_names
    unknown = [name for name in cmd_arguments if not (_accepted_names(command_id, name) & known)]
    if not unknown:
        return None

    reported = []
    for name in unknown:
        closest = get_close_matches(name, sorted(known), n=1, cutoff=0.6)
        reported.append(f"'{name}'" + (f" (did you mean '{closest[0]}'?)" if closest else ""))
    return (
        f"Unknown cmd_arguments for command '{command_id}': {', '.join(reported)}. "
        f"Declared parameter names: {', '.join(sorted(known))}"
        f" (mandatory: {', '.join(sorted(contract.mandatory)) or 'none'}). "
        "Keys of cmd_arguments are the parameter names from get_command_definitions; "
        "Perfecto ignores undeclared argument names instead of failing."
    )


def _format_bound(bound: Optional[float]) -> str:
    if isinstance(bound, float) and bound.is_integer():
        return str(int(bound))
    return str(bound)


def coerce_argument_value(value: Any, parameter: Optional[ParameterContract]) -> Any:
    """Normalize a constant to the spelling Perfecto persists.

    Every constant observed in a UI-authored script is a string, including INTEGER
    parameters ("2", not 2), so numbers are stringified. Enumerations are snapped to
    their declared casing.
    """
    if parameter is None:
        return value
    if isinstance(value, bool):
        # Not confirmed against a UI-authored boolean argument; consistent with every
        # other constant being a string.
        return "true" if value else "false"
    if isinstance(value, (int, float)) and parameter.is_integer:
        return str(int(value)) if float(value).is_integer() else str(value)
    if isinstance(value, str) and parameter.allowed_values:
        return parameter.match_allowed_value(value) or value
    return value


def _validate_argument_value(
        name: str,
        raw: Any,
        parameter: ParameterContract,
) -> Optional[str]:
    data_source = "CONSTANT"
    value: Any = raw
    if isinstance(raw, dict) and "data_source" in raw:
        data_source = str(raw.get("data_source") or "").upper()
        if parameter.data_sources and data_source not in parameter.data_sources:
            return (
                f"'{name}' does not accept data_source {data_source}; "
                f"accepted: {', '.join(sorted(parameter.data_sources))}."
            )
        if data_source != "CONSTANT":
            # Variable and DataTable bindings are resolved at execution time.
            return None
        value = raw.get("value")

    if value is None or isinstance(value, bool):
        pass
    elif parameter.is_integer:
        try:
            numeric = float(str(value).strip())
        except (TypeError, ValueError):
            return f"'{name}' expects a number ({parameter.data_type}), got {value!r}."
        if parameter.minimum is not None and numeric < parameter.minimum:
            return (
                f"'{name}' must be within {_format_bound(parameter.minimum)}.."
                f"{_format_bound(parameter.maximum)}, got {value!r}."
            )
        if parameter.maximum is not None and numeric > parameter.maximum:
            return (
                f"'{name}' must be within {_format_bound(parameter.minimum)}.."
                f"{_format_bound(parameter.maximum)}, got {value!r}."
            )

    if parameter.is_boolean and not isinstance(value, bool) and value is not None:
        if str(value).strip().casefold() not in (BOOLEAN_TRUE | BOOLEAN_FALSE):
            return f"'{name}' expects a boolean, got {value!r}."

    if parameter.allowed_values and isinstance(value, str) and value.strip():
        if parameter.match_allowed_value(value) is None:
            return (
                f"'{name}' must be one of {', '.join(parameter.allowed_values)}, got {value!r}."
            )
    return None


def _validate_occurrences(name: str, count: int, parameter: ParameterContract) -> Optional[str]:
    if count > parameter.max_occurrences:
        return (
            f"'{name}' accepts at most {parameter.max_occurrences} value(s), got {count}."
        )
    if count < parameter.min_occurrences:
        return (
            f"'{name}' needs at least {parameter.min_occurrences} values; "
            f"pass a list of {parameter.min_occurrences} or more."
        )
    return None


def validate_argument_values(
        command_id: str,
        cmd_arguments: Optional[dict[str, Any]],
        contract: Optional[CommandContract],
) -> Optional[str]:
    """Error message when a value breaks what the parameter declares.

    Names are checked by validate_argument_names; this only looks at values, and only
    for parameters the contract describes.
    """
    if not cmd_arguments or not contract or not contract.parameters:
        return None
    spec = get_command_spec(command_id)
    errors: list[str] = []
    for name, raw in spec.normalize_argument_names(cmd_arguments).items():
        parameter = contract.parameter(name)
        if parameter is None:
            continue
        occurrences = raw if isinstance(raw, list) else [raw]
        count_error = _validate_occurrences(name, len(occurrences), parameter)
        if count_error:
            errors.append(count_error)
            continue
        for occurrence in occurrences:
            error = _validate_argument_value(name, occurrence, parameter)
            if error:
                errors.append(error)
    if not errors:
        return None
    return (
        f"Invalid cmd_arguments for command '{command_id}': " + " ".join(errors)
        + " See view_test_step or get_command_definitions for accepted values."
    )


def _variable_binding_error(
        name: str,
        variable_name: Any,
        parameter: ParameterContract,
        script: dict[str, Any],
) -> Optional[str]:
    from tools.ai_scriptless.variables import (
        VARIABLE_DATA_TYPES_BY_PARAMETER_TYPE,
        bindable_values,
        describe_bindable_values,
        variable_type_label,
    )

    if not variable_name or not isinstance(variable_name, str):
        return (
            f"'{name}' is bound to a variable but no variable name was given; "
            f"pass {{\"data_source\": \"VARIABLE\", \"value\": \"<name>\"}}. "
            f"Defined: {describe_bindable_values(script)}."
        )

    bindable = bindable_values(script)
    data = bindable.get(variable_name)
    if data is None:
        return (
            f"'{name}' is bound to variable '{variable_name}', which this test does not define. "
            f"Defined: {describe_bindable_values(script)}. "
            "Add it with add_test_variable or bind an existing one."
        )

    expected = VARIABLE_DATA_TYPES_BY_PARAMETER_TYPE.get((parameter.data_type or "").upper())
    if expected and data.get("@type") not in expected:
        return (
            f"'{name}' is declared {parameter.data_type} but variable '{variable_name}' is a "
            f"{variable_type_label(data)}. Perfecto only binds a variable of the matching type; "
            f"create one with add_test_variable or pick another. "
            f"Defined: {describe_bindable_values(script)}."
        )
    return None


def validate_variable_bindings(
        command_id: str,
        cmd_arguments: Optional[dict[str, Any]],
        contract: Optional[CommandContract],
        script: dict[str, Any],
) -> Optional[str]:
    """Error message when an argument binds to a variable the script cannot provide.

    Needs the script, so this runs where the script is loaded: the variable must exist
    and its type must match the parameter, the same rule the UI enforces by only
    offering compatible variables in its picker.
    """
    if not cmd_arguments or not contract or not contract.parameters:
        return None
    spec = get_command_spec(command_id)
    errors: list[str] = []
    for name, raw in spec.normalize_argument_names(cmd_arguments).items():
        if not isinstance(raw, dict) or "data_source" not in raw:
            continue
        if str(raw.get("data_source") or "").upper() != "VARIABLE":
            continue
        parameter = contract.parameter(name)
        if parameter is None:
            continue
        error = _variable_binding_error(name, raw.get("value"), parameter, script)
        if error:
            errors.append(error)
    if not errors:
        return None
    return f"Invalid cmd_arguments for command '{command_id}': " + " ".join(errors)


def empty_mandatory_note(
        command_id: str,
        cmd_arguments: Optional[dict[str, Any]],
        contract: Optional[CommandContract],
) -> Optional[str]:
    """Note when a mandatory parameter is left empty (the step persists but does nothing)."""
    if not contract or not contract.mandatory:
        return None

    spec = get_command_spec(command_id)
    values: dict[str, Any] = {
        name: value for name, (_source, value) in spec.default_arguments_merged().items()
    }
    for name, value in spec.normalize_argument_names(cmd_arguments or {}).items():
        values[name] = _argument_value(value)

    empty = sorted(
        name for name in contract.mandatory
        if values.get(name) is None or (isinstance(values[name], str) and not values[name].strip())
    )
    if not empty:
        return None
    return (
        f"Mandatory parameter(s) left empty on '{command_id}': {', '.join(empty)}. "
        "The step is persisted but will not do anything until set with modify_command."
    )
