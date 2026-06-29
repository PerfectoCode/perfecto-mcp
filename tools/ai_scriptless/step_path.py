import re
from dataclasses import dataclass
from typing import Optional, Union

# Dot-separated positional paths (no spaces). Examples: 0, 2.0, 5.b0, 5.b0.1
# Segments are either a 0-based index (0, 1, 2) or a branch marker (b0=Then, b1=Else).
STEP_PATH_PATTERN = re.compile(r"^(?:\d+|b\d+)(?:\.(?:\d+|b\d+))*$")

StepPathInput = Union[str, "StepPath", None]


@dataclass(frozen=True)
class StepPath:
    parts: tuple[str, ...]

    @classmethod
    def parse(cls, step_path: str) -> "StepPath":
        if not step_path or step_path.strip() != step_path or " " in step_path:
            raise ValueError(
                "step_path must be a dot-separated positional path without spaces "
                "(e.g. 0, 2.0, 5.b0, 5.b0.1)"
            )
        if not STEP_PATH_PATTERN.match(step_path):
            raise ValueError(
                f"invalid step_path: {step_path!r}. Use dot-separated indices, e.g. 0, 2.0, 5.b0.1"
            )
        return cls(tuple(step_path.split(".")))

    @classmethod
    def root_index(cls, index: int) -> "StepPath":
        return cls((str(index),))

    def child_index(self, index: int) -> "StepPath":
        return StepPath((*self.parts, str(index)))

    def branch(self, branch_index: int) -> "StepPath":
        return StepPath((*self.parts, f"b{branch_index}"))

    @property
    def parent_prefix(self) -> str:
        if not self.parts:
            return ""
        return ".".join(self.parts) + "."

    def __str__(self) -> str:
        return ".".join(self.parts)


def coerce_step_path(step_path: StepPathInput) -> Optional[StepPath]:
    if step_path is None:
        return None
    if isinstance(step_path, StepPath):
        return step_path
    return StepPath.parse(step_path)


def validate_step_path(step_path: str) -> None:
    StepPath.parse(step_path)
