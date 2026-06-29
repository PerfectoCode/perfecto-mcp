"""Backward-compatible facade. Implementation lives in tools.ai_scriptless.commands."""

from tools.ai_scriptless.commands import *  # noqa: F403
from tools.ai_scriptless.commands import (
    COMMAND_SPECS,
    CommandSpec,
    command_id_from_element,
    get_command_spec,
    infer_element_type,
    parse_command_id,
)

__all__ = [
    "COMMAND_SPECS",
    "CommandSpec",
    "command_id_from_element",
    "get_command_spec",
    "infer_element_type",
    "parse_command_id",
]
