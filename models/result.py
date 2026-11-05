from typing import Any, Optional, List

from pydantic import BaseModel, Field, PrivateAttr


class BaseResult(BaseModel):
    result: Optional[Any] = Field(description="Result", default=None)
    total: Optional[int] = Field(description="Total available records", default=None)
    has_more: Optional[bool] = Field(description="More records are available", default=None)
    error: Optional[str] = Field(description="Error message", default=None)
    error_code: Optional[str] = Field(
        description="Machine-readable error code (e.g. SESSION_REQUIRED, SESSION_INVALID, SESSION_EXPIRED)",
        default=None,
    )
    session_id: Optional[str] = Field(
        description="Chat session this call ran in; keep passing it as session_id in every tool call",
        default=None,
    )
    info: Optional[List[str]] = Field(description="Info messages", default=None)
    warning: Optional[List[str]] = Field(description="Warning messages", default=None)
    tool_call_started_at: Optional[str] = Field(description="ISO timestamp when tool action started", default=None)
    tool_call_finished_at: Optional[str] = Field(description="ISO timestamp when tool action finished", default=None)
    tool_call_duration_ms: Optional[int] = Field(description="Tool action duration in milliseconds", default=None)
    debug: Optional[dict[str, Any]] = Field(description="Optional debug metrics for tool calls", default=None)
    # In-process only (never serialized): (task_id, scope) while a task is still running.
    _pending_task: Optional[tuple[str, Any]] = PrivateAttr(default=None)

    def mark_pending_task(self, task_id: str, scope: Any) -> None:
        self._pending_task = (task_id, scope)

    @property
    def pending_task(self) -> Optional[tuple[str, Any]]:
        return self._pending_task

    def append_warnings(self, messages: List[str]):
        if not self.warning:
            self.warning = []
        self.warning.extend(messages)

    def append_info(self, info: List[str]):
        if not self.info:
            self.info = []
        self.info.extend(info)

    def model_dump(self, **kwargs):
        return super().model_dump(exclude_none=True, **kwargs)

    def model_dump_json(self, **kwargs):
        return super().model_dump_json(exclude_none=True, **kwargs)

class PaginationResult(BaseResult):
    items: List[Any] = Field(description="Items", default=[])
    count: int = Field(description="Number of Items", default=0)
    total: Optional[int] = Field(description="Total Items", default=0)
    page: int = Field(description="Page index", default=0)
    offset: int = Field(description="Offset index", default=0)
    next_offset: int = Field(description="Next Offset index", default=0)
    has_more: bool = Field(description="Has More", default=0)
