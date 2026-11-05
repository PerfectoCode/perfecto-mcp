"""Process-wide context for dataframe materialization and async tasks."""
from __future__ import annotations

import contextvars

from config.ids import SIMPLE_ID_ALPHABET, SIMPLE_ID_LENGTH, random_id

_task_management_enabled = contextvars.ContextVar("task_management_enabled", default=False)
_result_format_context = contextvars.ContextVar("result_format_context", default="auto")
_disable_dataframe_materialization = contextvars.ContextVar(
    "disable_dataframe_materialization", default=False
)
_cache_bypass = contextvars.ContextVar("cache_bypass", default=False)

# Tool actions that must stay inline under result_format=auto.
TOOLS_ACTIONS_SKIP_AUTO_DATAFRAME = frozenset({
    "tasks_get",
    "tasks_list",
    "tasks_status",
    "tasks_cancel",
    "tasks_remove",
    "dataframes_list",
    "dataframes_get",
    "dataframes_schema_groups",
    "dataframes_query",
    "dataframes_remove",
    "dataframes_clear",
    "dataframes_sql_help",
    "version",
    "check_updates",
})


def generate_simple_id() -> str:
    return random_id(SIMPLE_ID_LENGTH)


def normalize_simple_id(simple_id: str) -> str:
    return str(simple_id).strip().lower()


def set_disable_dataframe_materialization(disabled: bool) -> contextvars.Token:
    return _disable_dataframe_materialization.set(bool(disabled))


def reset_disable_dataframe_materialization(token: contextvars.Token) -> None:
    _disable_dataframe_materialization.reset(token)


def set_result_format(result_format: str) -> contextvars.Token:
    return _result_format_context.set(result_format or "auto")


def reset_result_format(token: contextvars.Token) -> None:
    _result_format_context.reset(token)
