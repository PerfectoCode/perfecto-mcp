from dataclasses import dataclass, field
from typing import Any

_HANDSET_DUT: dict[str, tuple[str, Any]] = {"handsetId": ("VARIABLE", "DUT")}


@dataclass(frozen=True)
class CommandSpec:
    command_id: str
    element_type: str
    default_arguments: dict[str, tuple[str, Any]]
    argument_aliases: dict[str, str] = field(default_factory=dict)

    @property
    def error_policy(self) -> str:
        return "IGNORE" if self.element_type == "Validation" else "ABORT"

    def default_arguments_merged(self) -> dict[str, tuple[str, Any]]:
        return dict(self.default_arguments)

    def normalize_argument_names(self, arguments: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for name, value in arguments.items():
            normalized[self.argument_aliases.get(name, name)] = value
        return normalized

    def drop_superseded_aliases(self, arguments: dict[str, Any]) -> None:
        for alias, canonical in self.argument_aliases.items():
            if alias != canonical and canonical in arguments:
                arguments.pop(alias, None)


def parse_command_id(command_id: str) -> tuple[str, str]:
    if command_id.startswith("ai_"):
        return "ai", command_id[3:]
    if "_" in command_id:
        command, subcommand = command_id.split("_", 1)
        return command, subcommand
    return command_id, ""


def command_id_from_element(element: dict[str, Any]) -> str:
    command = element.get("command", "")
    subcommand = element.get("subcommand") or ""
    if subcommand:
        return f"{command}_{subcommand}"
    return command


def infer_element_type(command: str, subcommand: str) -> str:
    if command == "ai" and subcommand == "validation":
        return "Validation"
    if command == "checkpoint":
        return "Validation"
    return "Action"


def _command_spec(
        command_id: str,
        element_type: str,
        default_arguments: dict[str, tuple[str, Any]],
        argument_aliases: dict[str, str] | None = None,
) -> CommandSpec:
    return CommandSpec(
        command_id=command_id,
        element_type=element_type,
        default_arguments=default_arguments,
        argument_aliases=argument_aliases or {},
    )


COMMAND_SPECS: dict[str, CommandSpec] = {
    spec.command_id: spec
    for spec in (
        _command_spec("ai_user-action", "Action", {**_HANDSET_DUT, "action": ("CONSTANT", "")}),
        _command_spec("ai_validation", "Validation", {**_HANDSET_DUT, "validation": ("CONSTANT", "")}),
        _command_spec("ai_visual-comparison", "Action", {**_HANDSET_DUT, "name": ("CONSTANT", "")}),
        _command_spec("comment", "Action", {"text": ("CONSTANT", "")}),
        _command_spec(
            "wait",
            "Action",
            {"duration": ("CONSTANT", "1")},
            argument_aliases={"waitDuration": "duration"},
        ),
        _command_spec("handset_ready", "Action", dict(_HANDSET_DUT)),
        _command_spec("touch_tap", "Action", dict(_HANDSET_DUT)),
        _command_spec("checkpoint_text", "Validation", dict(_HANDSET_DUT)),
        _command_spec("checkpoint_image", "Validation", dict(_HANDSET_DUT)),
    )
}


def get_command_spec(command_id: str) -> CommandSpec:
    registered = COMMAND_SPECS.get(command_id)
    if registered is not None:
        return registered
    command, subcommand = parse_command_id(command_id)
    return CommandSpec(
        command_id=command_id,
        element_type=infer_element_type(command, subcommand),
        default_arguments=dict(_HANDSET_DUT),
    )
