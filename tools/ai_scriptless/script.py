import copy
from typing import Any, Optional, Union

from tools.ai_scriptless.elements import new_empty_script, strip_non_api_script_fields
from tools.ai_scriptless.step_path import StepPathInput
from tools.ai_scriptless.tree import (
    delete_element_by_path,
    find_container_by_path,
    find_element_by_path,
    find_step_path_for_element,
    insert_flow_element,
    move_element_by_path,
    set_condition_expression,
    set_element_enabled,
    update_flow_element_counts,
)
from tools.ai_scriptless.variables import (
    add_script_variable,
    delete_script_variable,
    find_variable,
    list_script_variables,
    modify_script_variable,
)

ScriptInput = Union["Script", dict[str, Any]]


def coerce_script_dict(script: ScriptInput) -> dict[str, Any]:
    if isinstance(script, Script):
        return script.to_dict()
    return script


class Script:
    """In-memory aggregate root for an AI Scriptless script payload."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def empty(cls) -> "Script":
        return cls(new_empty_script())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Script":
        return cls(copy.deepcopy(data))

    @classmethod
    def wrap(cls, data: dict[str, Any]) -> "Script":
        """Wrap an existing dict for in-place mutation (e.g. load_and_mutate)."""
        return cls(data)

    def to_dict(self) -> dict[str, Any]:
        return self._data

    def copy(self) -> "Script":
        return Script.from_dict(self._data)

    @property
    def flow_elements(self) -> list[dict[str, Any]]:
        return self._data.setdefault("flowElements", [])

    @property
    def variables(self) -> list[dict[str, Any]]:
        return self._data.setdefault("variables", [])

    @property
    def flow_element_count(self) -> int:
        return len(self.flow_elements)

    def prepare_for_persist(self) -> None:
        strip_non_api_script_fields(self._data)
        update_flow_element_counts(self._data)

    def find_step_path_for_element(self, target: dict[str, Any]) -> Optional[str]:
        return find_step_path_for_element(self._data, target)

    def find_element_by_path(
            self,
            step_path: StepPathInput,
    ) -> Optional[tuple[list[dict[str, Any]], int, dict[str, Any]]]:
        return find_element_by_path(self._data, step_path)

    def find_container_by_path(self, step_path: StepPathInput) -> Optional[dict[str, Any]]:
        return find_container_by_path(self._data, step_path)

    def insert_flow_element(
            self,
            element: dict[str, Any],
            after_path: StepPathInput = None,
            parent_path: StepPathInput = None,
    ) -> None:
        insert_flow_element(self._data, element, after_path=after_path, parent_path=parent_path)

    def delete_element_by_path(self, step_path: StepPathInput) -> None:
        delete_element_by_path(self._data, step_path)

    def set_element_enabled(self, step_path: StepPathInput, enabled: bool) -> None:
        set_element_enabled(self._data, step_path, enabled)

    def set_condition_expression(self, step_path: StepPathInput, expression: str) -> None:
        set_condition_expression(self._data, step_path, expression)

    def move_element_by_path(
            self,
            step_path: StepPathInput,
            after_path: StepPathInput = None,
            parent_path: StepPathInput = None,
    ) -> None:
        move_element_by_path(
            self._data,
            step_path,
            after_path=after_path,
            parent_path=parent_path,
        )

    def list_variables(self) -> list[dict[str, Any]]:
        return list_script_variables(self._data)

    def find_variable(self, variable_name: str) -> Optional[tuple[int, dict[str, Any]]]:
        return find_variable(self._data, variable_name)

    def add_variable(
            self,
            name: str,
            variable_type: str,
            value: Any,
            set_at_runtime: bool = False,
    ) -> dict[str, Any]:
        return add_script_variable(
            self._data,
            name,
            variable_type,
            value,
            set_at_runtime=set_at_runtime,
        )

    def modify_variable(
            self,
            variable_name: str,
            value: Optional[Any] = None,
            variable_type: Optional[str] = None,
            set_at_runtime: Optional[bool] = None,
    ) -> dict[str, Any]:
        return modify_script_variable(
            self._data,
            variable_name,
            value=value,
            variable_type=variable_type,
            set_at_runtime=set_at_runtime,
        )

    def delete_variable(self, variable_name: str) -> None:
        delete_script_variable(self._data, variable_name)
