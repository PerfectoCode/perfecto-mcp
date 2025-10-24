from typing import Any, Optional, List

from pydantic import BaseModel, Field


class BaseResult(BaseModel):
    result: Optional[Any] = Field(description="Result", default=None)
    error: Optional[str] = Field(description="Error message", default=None)
    info: Optional[List[str]] = Field(description="Info messages", default=None)
    warning: Optional[List[str]] = Field(description="Warning messages", default=None)

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
