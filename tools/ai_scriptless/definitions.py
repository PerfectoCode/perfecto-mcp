"""Cross-check between command parameters (command repository API) and command
arguments (script model).

The command repository declares ``mandatoryParameters`` / ``optionalParameters``;
the script persists those same names as ``FunctionArgument`` entries. The names
match, the vocabulary does not: a parameter is the declaration, an argument is
the assigned value. Perfecto silently ignores arguments whose name is not
declared, so an unknown name only shows up as a step that does nothing at
execution time. These helpers turn that into an error at authoring time.

Validation fails open on purpose: when the definitions API is unreachable or
returns no declared parameters, authoring keeps working unvalidated rather than
becoming unavailable.
"""

import asyncio
from difflib import get_close_matches
from typing import Any, Optional

from config import perfecto
from config.token import PerfectoToken
from tools.ai_scriptless.commands import get_command_spec
from tools.utils import api_request

# (cloud_name, command_id) -> (mandatory, optional) names, or None when unknown.
DeclaredParameters = tuple[frozenset[str], frozenset[str]]

_declared_parameters_cache: dict[tuple[str, str], Optional[DeclaredParameters]] = {}
_cache_guard = asyncio.Lock()


def reset_declared_parameters_cache() -> None:
    """Drop memoized definitions (used by tests and after a cloud switch)."""
    _declared_parameters_cache.clear()


async def _fetch_declared_parameters(
        token: PerfectoToken,
        command_id: str,
) -> Optional[DeclaredParameters]:
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
        mandatory = frozenset(definition.mandatory_parameters)
        optional = frozenset(definition.optional_parameters)
        # A definition with no declared parameter carries no usable contract.
        if not mandatory and not optional:
            return None
        return mandatory, optional
    return None


async def declared_parameters(
        token: Optional[PerfectoToken],
        command_id: str,
) -> Optional[DeclaredParameters]:
    """Declared parameter names for command_id, or None when unavailable."""
    if not token or not command_id:
        return None
    cache_key = (token.cloud_name, command_id)
    async with _cache_guard:
        if cache_key in _declared_parameters_cache:
            return _declared_parameters_cache[cache_key]
    declared = await _fetch_declared_parameters(token, command_id)
    async with _cache_guard:
        _declared_parameters_cache[cache_key] = declared
    return declared


def _accepted_names(command_id: str, name: str) -> set[str]:
    """The name plus its known aliases; the repository may declare any of them."""
    spec = get_command_spec(command_id)
    names = {name, spec.argument_aliases.get(name, name)}
    names |= {alias for alias, canonical in spec.argument_aliases.items() if canonical == name}
    return names


def _argument_value(value: Any) -> Any:
    if isinstance(value, dict) and "data_source" in value:
        return value.get("value")
    return value


def validate_argument_names(
        command_id: str,
        cmd_arguments: Optional[dict[str, Any]],
        declared: Optional[DeclaredParameters],
) -> Optional[str]:
    """Error message when cmd_arguments carries names the command does not declare."""
    if not cmd_arguments or not declared:
        return None
    mandatory, optional = declared
    known = mandatory | optional
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
        f" (mandatory: {', '.join(sorted(mandatory)) or 'none'}). "
        "Keys of cmd_arguments are the parameter names from get_command_definitions; "
        "Perfecto ignores undeclared argument names instead of failing."
    )


def empty_mandatory_note(
        command_id: str,
        cmd_arguments: Optional[dict[str, Any]],
        declared: Optional[DeclaredParameters],
) -> Optional[str]:
    """Note when a mandatory parameter is left empty (the step persists but does nothing)."""
    if not declared:
        return None
    mandatory, _optional = declared
    if not mandatory:
        return None

    spec = get_command_spec(command_id)
    values: dict[str, Any] = {
        name: value for name, (_source, value) in spec.default_arguments_merged().items()
    }
    for name, value in spec.normalize_argument_names(cmd_arguments or {}).items():
        values[name] = _argument_value(value)

    empty = sorted(
        name for name in mandatory
        if values.get(name) is None or (isinstance(values[name], str) and not values[name].strip())
    )
    if not empty:
        return None
    return (
        f"Mandatory parameter(s) left empty on '{command_id}': {', '.join(empty)}. "
        "The step is persisted but will not do anything until set with modify_command."
    )
