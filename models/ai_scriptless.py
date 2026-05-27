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


class ScriptVariableSummary(BaseModel):
    name: str = Field(description="Variable name")
    type: str = Field(description="Variable type (string, number, boolean, secured_string, etc.)")
    value: Optional[Any] = Field(description="Variable value when readable", default=None)
    secured: bool = Field(description="Whether the value is secured", default=False)
    set_at_runtime: bool = Field(description="True when value is provided at execution time", default=False)


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