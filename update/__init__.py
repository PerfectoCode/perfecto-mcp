"""Manual in-place updater for frozen Perfecto MCP binaries (tufup-inspired)."""

from update.flow import run_interactive_update
from update.processes import RunningProcess, find_other_instances

__all__ = [
    "RunningProcess",
    "find_other_instances",
    "run_interactive_update",
]
