from typing import Any, List, Optional

from pydantic import BaseModel, Field


class ScriptFlowElement(BaseModel):
    type: str = Field(description="Perfecto @type (Action, Validation, Loop, etc.)")
    name: str = Field(description="Display name for the step")
    command: Optional[str] = Field(description="Command namespace", default=None)
    subcommand: Optional[str] = Field(description="Command subcommand", default=None)
    active: bool = Field(description="Whether the step is enabled (not excluded)", default=True)
    step_path: Optional[str] = Field(
        description="Dot-separated positional path (e.g. 0, 2.0, 5.b0.1); derived from tree position",
        default=None,
    )
    children: List["ScriptFlowElement"] = Field(description="Nested flow elements", default_factory=list)


class ScriptParameter(BaseModel):
    name: str = Field(description="Parameter name")
    type: str = Field(description="Parameter data type")


class ScriptStepArgument(BaseModel):
    name: str = Field(description="Argument name; use it as the cmd_arguments key on modify_command")
    value: Optional[Any] = Field(description="Current value ('<secured>' when secured)", default=None)
    data_source: Optional[str] = Field(
        description="Where the value comes from: CONSTANT, VARIABLE (a script variable) or DATATABLE",
        default=None,
    )
    parameter_type: Optional[str] = Field(
        description="Declared data type (STRING, INTEGER, BOOLEAN, HANDSET, ...)", default=None
    )
    mandatory: Optional[bool] = Field(description="Whether the command declares it mandatory", default=None)
    declared: bool = Field(
        description="False when the command definition does not declare this name (Perfecto ignores it)",
        default=True,
    )
    allowed_data_sources: List[str] = Field(
        description="Data sources the parameter accepts", default_factory=list
    )
    allowed_values: List[str] = Field(
        description="Accepted values when the parameter is an enumeration or combo", default_factory=list
    )
    value_range: Optional[str] = Field(description="Accepted numeric range as 'min..max'", default=None)
    label: Optional[str] = Field(description="Display label used by the UI", default=None)
    declared_label: Optional[str] = Field(
        description="Label the command definition declares, when the UI renames it", default=None
    )
    table_name: Optional[str] = Field(
        description="DataTable the argument reads from (data_source DATATABLE)", default=None
    )
    column: Optional[str] = Field(
        description="DataTable column the argument reads from (data_source DATATABLE)", default=None
    )


class ScriptStepParameter(BaseModel):
    """A parameter the command declares that the step does not currently set."""

    name: str = Field(description="Parameter name; use it as the cmd_arguments key on modify_command")
    parameter_type: Optional[str] = Field(description="Declared data type", default=None)
    mandatory: bool = Field(description="Whether the command declares it mandatory", default=False)
    default_value: Optional[Any] = Field(description="Value Perfecto applies when unset", default=None)
    allowed_data_sources: List[str] = Field(
        description="Data sources the parameter accepts", default_factory=list
    )
    allowed_values: List[str] = Field(
        description="Accepted values when the parameter is an enumeration or combo", default_factory=list
    )
    value_range: Optional[str] = Field(description="Accepted numeric range as 'min..max'", default=None)
    label: Optional[str] = Field(description="Display label used by the UI", default=None)
    declared_label: Optional[str] = Field(
        description="Label the command definition declares, when the UI renames it", default=None
    )
    help_text: Optional[str] = Field(description="Parameter help text", default=None)


class ScriptStepDetail(BaseModel):
    item_key: str = Field(description="Script itemKey the step belongs to")
    step_path: str = Field(description="Dot-separated positional path of the step")
    type: str = Field(description="Perfecto @type (Action, Validation, LogicalStep, Loop, IfStatement, Branch)")
    name: str = Field(description="Display name, same as in view_test_structure")
    command_id: Optional[str] = Field(description="Command ID for get_command_definitions", default=None)
    command: Optional[str] = Field(description="Command namespace", default=None)
    subcommand: Optional[str] = Field(description="Command subcommand", default=None)
    active: bool = Field(description="False when the step is excluded from the run", default=True)
    error_policy: Optional[str] = Field(
        description="ABORT aborts the test on failure, IGNORE only reports it", default=None
    )
    comment: Optional[str] = Field(description="Step comment", default=None)
    arguments: List[ScriptStepArgument] = Field(
        description="Arguments currently persisted on the step", default_factory=list
    )
    unset_parameters: List[ScriptStepParameter] = Field(
        description="Declared parameters the step does not set yet", default_factory=list
    )
    label: Optional[str] = Field(description="Container label (LogicalStep or IfStatement)", default=None)
    statement_step_path: Optional[str] = Field(
        description=(
            "For an IfStatement: the step whose result decides the branch (the UI's 'Statement'). "
            "It is the preceding sibling carrying errorPolicy CATCH; None means the condition has "
            "nothing to evaluate yet."
        ),
        default=None,
    )
    loop_count: Optional[int] = Field(description="Iterations of a Loop that repeats a fixed number of times", default=None)
    loop_variable: Optional[str] = Field(
        description="Number variable that decides the iterations of a Loop, when it is variable-driven",
        default=None,
    )
    children: List[str] = Field(
        description="Step paths of direct children, for containers", default_factory=list
    )
    notes: List[str] = Field(description="Editing notes for this step", default_factory=list)


class ScriptVariableSummary(BaseModel):
    name: str = Field(description="Variable name")
    type: str = Field(description="Variable type (string, number, boolean, secured_string, etc.)")
    value: Optional[Any] = Field(description="Variable value when readable", default=None)
    secured: bool = Field(description="Whether the value is secured", default=False)
    set_at_runtime: bool = Field(
        description=(
            "True for a runtime variable: the stored value is a default, supplied when the run starts and "
            "free to change during execution. False means the value is constant for the whole run."
        ),
        default=False,
    )


class TestStructure(BaseModel):
    item_key: str = Field(description="Script itemKey")
    parameters: List[ScriptParameter] = Field(description="Test parameters", default_factory=list)
    model_version: Optional[str] = Field(description="Script model version", default=None)
    flow_elements: List[ScriptFlowElement] = Field(description="Root flow elements", default_factory=list)


class CommandCatalogEntry(BaseModel):
    command_id: str = Field(description="Command identifier for definitions API")
    name: str = Field(description="Display name")
    path: str = Field(description="Catalog path")
    status: Optional[str] = Field(description="Command status (GA, DRAFT, etc.)", default=None)
    category: Optional[str] = Field(description="Parent category name", default=None)


class SnapshotSummary(BaseModel):
    key: str = Field(description="Snapshot identifier (UUID for history, or '<current>' for the live script marker)")
    version: Optional[str] = Field(description="Snapshot version label", default=None)
    comment: Optional[str] = Field(description="User comment from save with comment (typically on '<current>' only)", default=None)
    created_by: Optional[str] = Field(description="User who created the snapshot", default=None)
    created_time: Optional[str] = Field(description="Creation timestamp", default=None)
    is_current: bool = Field(description="True when key is '<current>' (live script marker, not openable via view_snapshot)", default=False)


class SnapshotListResult(BaseModel):
    test_id: Optional[str] = Field(description="Test itemKey queried", default=None)
    count: int = Field(description="Number of snapshot entries returned")
    snapshots: List[SnapshotSummary] = Field(description="Snapshot entries including '<current>' marker", default_factory=list)
    notes: List[str] = Field(description="Behavior notes for interpreting snapshot history", default_factory=list)


class CommandDefinitionSummary(BaseModel):
    command_id: str = Field(description="Command identifier")
    name: str = Field(description="Display name")
    mandatory_parameters: List[str] = Field(description="Required parameter names", default_factory=list)
    optional_parameters: List[str] = Field(description="Optional parameter names", default_factory=list)
    help_text: Optional[str] = Field(description="Help text", default=None)
    raw: Optional[dict[str, Any]] = Field(description="Full definition payload", default=None)


ScriptFlowElement.model_rebuild()