"""Session dataframe and async task actions exposed on perfecto_tools."""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, Optional

from mcp.server.fastmcp import Context

from config.storage import SessionScope, SessionScopeResolverPort, SessionStoragePort
from models.manager import Manager
from models.result import BaseResult
from tools.async_task_manager import (
    cancel_task,
    get_task_record,
    is_active_status,
    is_terminal_status,
    list_tasks,
    remove_task,
    task_snapshot,
)
from tools.dataframe_manager import (
    INVALID_RESULT_FORMAT_ERROR,
    clear_dataframes,
    get_dataframe_metadata,
    get_sql_capabilities,
    group_dataframe_schemas,
    list_dataframes_metadata,
    normalize_result_format,
    query_dataframes,
    register_dataframe,
    remove_dataframes,
    serialize_result_to_compact_json,
    stored_as_dataframe_payload,
)
from tools.task_runtime import run_as_task

class DataTools(Manager):
    """Session-scoped dataframe + async task tools backed by SessionStoragePort."""

    def __init__(
            self,
            ctx: Context,
            session_storage: SessionStoragePort,
            scope_resolver: SessionScopeResolverPort,
    ):
        super().__init__(ctx)
        self.session_storage = session_storage
        self.scope_resolver = scope_resolver

    def _scope(self) -> SessionScope:
        return self.scope_resolver.resolve()

    @staticmethod
    def _poll_args_error(wait_for_terminal_ms: int, poll_interval_ms: int) -> Optional[BaseResult]:
        if wait_for_terminal_ms < 0:
            return BaseResult(error="wait_for_terminal_ms must be greater than or equal to 0.")
        if poll_interval_ms <= 0:
            return BaseResult(error="poll_interval_ms must be greater than 0.")
        return None

    @staticmethod
    def _should_continue_polling(status: str) -> bool:
        return status in {"parking", "working", "input_required"}

    @staticmethod
    def _to_snake_case(value: str) -> str:
        s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
        return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    @classmethod
    def _operation_name(cls, action_payload: Dict[str, Any]) -> str:
        manager = str(action_payload.get("manager", "tool"))
        method = str(action_payload.get("method", "action"))
        tool_name = manager[:-7] if manager.endswith("Manager") else manager
        tool_name = cls._to_snake_case(tool_name)
        return f"{tool_name}.{method}"


    async def _batch_summary_line(self) -> str:
        records = await list_tasks(scope=self._scope())
        counts = {
            "completed": 0,
            "working": 0,
            "parking": 0,
            "failed": 0,
            "cancelled": 0,
            "input_required": 0,
        }
        for record in records:
            status = str(record.status).lower()
            if status in counts:
                counts[status] += 1
        summary = (
            f"batch summary: total={len(records)} completed={counts['completed']} "
            f"working={counts['working']} parking={counts['parking']} failed={counts['failed']}"
        )
        if counts["cancelled"] > 0:
            summary += f" cancelled={counts['cancelled']}"
        if counts["input_required"] > 0:
            summary += f" input_required={counts['input_required']}"
        return summary

    @classmethod
    def _task_status_line(
            cls,
            task_record,
            poll_count: Optional[int],
            elapsed_seconds: int,
            next_poll_seconds: Optional[float],
            window_seconds: Optional[float] = None,
            include_polling_prefix: bool = True,
    ) -> str:
        operation = cls._operation_name(task_record.action)
        prefix = "Polling " if include_polling_prefix else ""
        line = f"{prefix}{task_record.task_id}[{operation}] ({task_record.status})"
        if poll_count is not None:
            line += f" attempt={poll_count}"
        line += f" elapsed={elapsed_seconds}s"
        if window_seconds is not None:
            line += f"/{int(window_seconds)}s"
        if next_poll_seconds is not None and cls._should_continue_polling(task_record.status):
            line += f" next={int(next_poll_seconds)}s"
        if task_record.status == "parking" and task_record.status_message:
            line += f" note={repr(task_record.status_message)}"
        return line

    async def _polling_message(
            self,
            task_record,
            poll_count: int,
            elapsed_seconds: int,
            next_poll_seconds: float,
            window_seconds: float,
    ) -> str:
        line = self._task_status_line(
            task_record=task_record,
            poll_count=poll_count,
            elapsed_seconds=elapsed_seconds,
            next_poll_seconds=next_poll_seconds,
            window_seconds=window_seconds,
            include_polling_prefix=True,
        )
        return f"{line} | {await self._batch_summary_line()}"

    async def _polling_finished_message(self, task_record, elapsed_seconds: int) -> str:
        line = self._task_status_line(
            task_record=task_record,
            poll_count=None,
            elapsed_seconds=elapsed_seconds,
            next_poll_seconds=None,
            window_seconds=None,
            include_polling_prefix=True,
        )
        return f"{line} | {await self._batch_summary_line()}"

    async def _wait_for_terminal(
            self,
            task_id: str,
            task_record,
            wait_for_terminal_ms: int,
            poll_interval_ms: int,
    ):
        """Poll Storage until terminal, timeout, or the record disappears.

        Returns (record, polling_exhausted, error_result). error_result is set
        when the task vanishes mid-poll.
        """
        if wait_for_terminal_ms <= 0 or is_terminal_status(task_record.status):
            return task_record, False, None

        scope = self._scope()
        start_time = time.monotonic()
        wait_seconds = wait_for_terminal_ms / 1000.0
        poll_seconds = poll_interval_ms / 1000.0
        attempt = 0
        polling_exhausted = False

        while True:
            task_record = await get_task_record(task_id, scope=scope)
            if not task_record:
                return None, False, BaseResult(error=f"Task ID {task_id} was not found.")
            if is_terminal_status(task_record.status):
                break

            elapsed = time.monotonic() - start_time
            if elapsed >= wait_seconds:
                polling_exhausted = True
                break

            attempt += 1
            progress = min(100.0, (elapsed / wait_seconds) * 100.0) if wait_seconds > 0 else 100.0
            try:
                await self.ctx.report_progress(
                    progress=progress,
                    total=100.0,
                    message=await self._polling_message(
                        task_record=task_record,
                        poll_count=attempt,
                        elapsed_seconds=int(elapsed),
                        next_poll_seconds=poll_seconds,
                        window_seconds=wait_seconds,
                    ),
                )
            except Exception:
                pass

            remaining = wait_seconds - elapsed
            await asyncio.sleep(min(poll_seconds, remaining))

        try:
            final_elapsed = min(wait_seconds, time.monotonic() - start_time)
            await self.ctx.report_progress(
                progress=100.0,
                total=100.0,
                message=await self._polling_finished_message(
                    task_record=task_record,
                    elapsed_seconds=int(final_elapsed),
                ),
            )
        except Exception:
            pass

        return task_record, polling_exhausted, None

    async def tasks_get(
            self,
            task_id: str,
            remove_on_terminal: bool = True,
            wait_for_terminal_ms: int = 0,
            poll_interval_ms: int = 1000,
    ) -> BaseResult:
        if error := self._poll_args_error(wait_for_terminal_ms, poll_interval_ms):
            return error

        scope = self._scope()
        task_record = await get_task_record(task_id, scope=scope)
        if not task_record:
            return BaseResult(error=f"Task ID {task_id} was not found.")

        task_record, polling_exhausted, missing = await self._wait_for_terminal(
            task_id, task_record, wait_for_terminal_ms, poll_interval_ms,
        )
        if missing:
            return missing

        terminal = is_terminal_status(task_record.status)
        snapshot = task_snapshot(task_record, include_result=terminal)
        snapshot["should_continue_polling"] = self._should_continue_polling(task_record.status)
        snapshot["next_poll_after_ms"] = poll_interval_ms if snapshot["should_continue_polling"] else 0

        if terminal and remove_on_terminal:
            await remove_task(task_id, scope=scope)
            return BaseResult(
                result=[snapshot],
                info=[
                    "Task result retrieved successfully and removed automatically from the task registry. "
                    "It will not be available in subsequent queries."
                ],
            )

        if terminal:
            return BaseResult(
                result=[snapshot],
                info=[
                    "Task result retrieved successfully and kept in the task registry. "
                    "Use tasks_remove to delete it when no longer needed."
                ],
            )

        return BaseResult(
            result=[snapshot],
            info=[
                (
                    "Task is still in progress after the polling window. Query tasks_status again in a few moments."
                    if polling_exhausted
                    else "Task is still in progress. Query tasks_status again in a few moments to check updated state."
                )
            ],
        )

    async def tasks_status(
            self,
            task_id: str,
            wait_for_terminal_ms: int = 0,
            poll_interval_ms: int = 1000,
    ) -> BaseResult:
        if error := self._poll_args_error(wait_for_terminal_ms, poll_interval_ms):
            return error

        task_record = await get_task_record(task_id, scope=self._scope())
        if not task_record:
            return BaseResult(error=f"Task ID {task_id} was not found.")

        task_record, polling_exhausted, missing = await self._wait_for_terminal(
            task_id, task_record, wait_for_terminal_ms, poll_interval_ms,
        )
        if missing:
            return missing

        snapshot = task_snapshot(task_record, include_result=False)
        snapshot["should_continue_polling"] = self._should_continue_polling(task_record.status)
        snapshot["next_poll_after_ms"] = poll_interval_ms if snapshot["should_continue_polling"] else 0
        info_message = (
            "Task is terminal. Use tasks_get to retrieve task_result when needed."
            if is_terminal_status(task_record.status)
            else (
                "Task is still in progress after the polling window. Query tasks_status again in a few moments."
                if polling_exhausted
                else "Task is still in progress. Query tasks_status again in a few moments to check updated state."
            )
        )
        return BaseResult(result=[snapshot], info=[info_message])

    async def tasks_list(
            self,
            status: Optional[str] = None,
            status_list: Optional[list[str]] = None,
    ) -> BaseResult:
        filters = status_list if status_list else ([status] if status else None)
        records = await list_tasks(filters, scope=self._scope())
        snapshots = []
        for record in records:
            base_snapshot = task_snapshot(record, include_result=False)
            snapshots.append(
                {
                    "task_id": record.task_id,
                    "operation": self._operation_name(record.action),
                    "status": record.status,
                    "status_message": record.status_message,
                    "created_at": record.created_at,
                    "created_at_iso": base_snapshot["created_at_iso"],
                    "last_updated_at": record.last_updated_at,
                    "last_updated_at_iso": base_snapshot["last_updated_at_iso"],
                    "started_running_at": record.started_running_at,
                    "started_running_at_iso": base_snapshot["started_running_at_iso"],
                    "finished_at": record.finished_at,
                    "finished_at_iso": base_snapshot["finished_at_iso"],
                    "time_to_live_ms": record.time_to_live_ms,
                }
            )
        return BaseResult(result=snapshots, total=len(snapshots), has_more=False)

    async def tasks_cancel(self, task_id: str) -> BaseResult:
        scope = self._scope()
        prior = await get_task_record(task_id, scope=scope)
        if not prior:
            return BaseResult(error=f"Task ID {task_id} was not found.")
        was_terminal = is_terminal_status(prior.status)
        had_local_handle = bool(prior.asyncio_task and not prior.asyncio_task.done())

        task_record = await cancel_task(task_id, scope=scope)
        if not task_record:
            return BaseResult(error=f"Task ID {task_id} was not found.")

        if was_terminal:
            info = (
                f"Task was already terminal ({prior.status}); status was left unchanged. "
                "Cancel does not rewrite completed/failed tasks."
            )
        elif had_local_handle:
            info = (
                "Task cancellation was requested on this worker's local asyncio handle."
            )
        else:
            info = (
                "Cancel was recorded in session Storage, but this worker has no local "
                "asyncio handle. Hosted execution affinity is process-local: the owning "
                "worker may still run the coroutine to completion and overwrite status."
            )
        return BaseResult(
            result=[task_snapshot(task_record, include_result=True)],
            info=[info],
        )

    async def tasks_remove(self, task_id: str) -> BaseResult:
        scope = self._scope()
        task_record = await get_task_record(task_id, scope=scope)
        if not task_record:
            return BaseResult(error=f"Task ID {task_id} was not found.")

        cancel_requested = False
        if is_active_status(task_record.status):
            cancel_requested = True
            await cancel_task(task_id, scope=scope)
            if task_record.asyncio_task:
                try:
                    await asyncio.wait_for(asyncio.shield(task_record.asyncio_task), timeout=0.2)
                except asyncio.TimeoutError:
                    pass
                except asyncio.CancelledError:
                    pass

        snapshot = task_snapshot(task_record, include_result=is_terminal_status(task_record.status))
        removed = await remove_task(task_id, scope=scope)
        if not removed:
            return BaseResult(error=f"Task ID {task_id} could not be removed.")

        info_message = (
            "Task was active. Cancellation was requested before removal."
            if cancel_requested
            else "Task was removed from task registry."
        )
        return BaseResult(
            result=[{
                "task_id": task_id,
                "removed": True,
                "cancel_requested": cancel_requested,
                "task_snapshot": snapshot,
            }],
            info=[info_message],
        )

    @run_as_task()
    async def dataframes_list(self) -> BaseResult:
        scope = self._scope()
        metadata = await list_dataframes_metadata(
            session_storage=self.session_storage,
            scope=scope,
            include_schema=False,
        )
        return BaseResult(
            result=metadata,
            total=len(metadata),
            has_more=False,
            info=[
                "Schema is omitted in dataframes_list to reduce payload size.",
                "Use dataframes_schema_groups to compare shared/different schemas across dataframes.",
                "Use dataframes_get for full metadata and schema of a specific dataframe.",
            ],
        )

    @run_as_task()
    async def dataframes_get(self, dataframe_id: str) -> BaseResult:
        scope = self._scope()
        metadata = await get_dataframe_metadata(
            dataframe_id,
            session_storage=self.session_storage,
            scope=scope,
        )
        if not metadata:
            return BaseResult(
                error=(
                    f"Dataframe ID {dataframe_id} was not found. "
                    "Use dataframes_list to discover available dataframes."
                )
            )
        return BaseResult(result=[metadata])

    @run_as_task()
    async def dataframes_schema_groups(
            self,
            dataframe_id_list: Optional[list[str]] = None,
    ) -> BaseResult:
        scope = self._scope()
        grouped = await group_dataframe_schemas(
            session_storage=self.session_storage,
            scope=scope,
            dataframe_id_list=dataframe_id_list,
        )
        mandatory_review_groups = [
            grp for grp in grouped.get("groups", [])
            if isinstance(grp, dict) and str(grp.get("varying_columns", "")).strip()
        ]
        info_messages = [
            "Grouped dataframe schemas by top-level contract and per-column schema variations.",
            "Dataframe ID lists are deduplicated in 'df_sets'; groups and variations reference them via 'df_ref'.",
            "If dataframe_id_list is omitted, all current dataframes are included.",
        ]
        if mandatory_review_groups:
            info_messages.append(
                "CRITICAL: Column variations were detected. Perform mandatory detailed schema "
                "review for varying columns before the final query."
            )
        info_messages.append(
            "IMPORTANT: Before planning and executing the final dataframe query, "
            "call dataframes_sql_help synchronously in a separate call."
        )
        return BaseResult(result=[grouped], info=info_messages)

    @run_as_task()
    async def dataframes_query(
            self,
            sql: str,
            output_format: str = "matrix",
            result_format: str = "auto",
    ) -> BaseResult:
        scope = self._scope()
        normalized_result_format = normalize_result_format(result_format)
        if normalized_result_format == "invalid":
            return BaseResult(error=INVALID_RESULT_FORMAT_ERROR)
        # Store path always queries as records so register_dataframe can rebuild rows.
        effective_output_format = (
            "records" if normalized_result_format == "dataframe" else output_format
        )
        info_messages = [
            "Query executed successfully against the session SQL context.",
            "ORDER BY + LIMIT + OFFSET are mandatory in every dataframe query.",
            "Use a prudent default page size of up to 100 rows (for example, LIMIT 100 OFFSET 0), "
            "then continue paging as needed.",
        ]
        query_response = await query_dataframes(
            sql,
            session_storage=self.session_storage,
            scope=scope,
            output_format=effective_output_format,
        )
        if query_response.get("error"):
            return BaseResult(error=query_response["error"])

        if normalized_result_format == "dataframe":
            rows = query_response["result"] or []
            try:
                json_size_chars = len(serialize_result_to_compact_json(rows))
            except Exception as exc:
                return BaseResult(error=f"Could not serialize query result: {exc}")
            metadata = await register_dataframe(
                result=rows,
                origin_manager="perfecto_tools",
                origin_action="dataframes_query",
                json_size_chars=json_size_chars,
                session_storage=self.session_storage,
                scope=scope,
            )
            return BaseResult(
                result=[stored_as_dataframe_payload(metadata)],
                info=info_messages + [
                    "result_format=dataframe stored the query output as a new session dataframe."
                ],
            )

        return BaseResult(
            result=query_response["result"],
            total=query_response["rows"],
            has_more=False,
            info=info_messages,
        )

    @run_as_task()
    async def dataframes_remove(self, dataframe_id_list: list[str]) -> BaseResult:
        empty_list_error = (
            "Missing required args for action 'dataframes_remove': "
            "dataframe_id_list must be a non-empty list of dataframe IDs."
        )
        if not dataframe_id_list or not isinstance(dataframe_id_list, list):
            return BaseResult(error=empty_list_error)
        ids = [str(df_id).strip() for df_id in dataframe_id_list if str(df_id).strip()]
        if not ids:
            return BaseResult(error=empty_list_error)

        unique_ids = list(dict.fromkeys(ids))
        outcome = await remove_dataframes(unique_ids, self.session_storage, self._scope())
        removed_ids = set(outcome["removed"])
        missing_ids = outcome["missing"]
        removed_count = len(outcome["removed"])
        removed_results = [
            {"dataframe_id": df_id, "removed": df_id in removed_ids}
            for df_id in unique_ids
        ]

        if len(unique_ids) == 1 and removed_count == 0:
            only_id = unique_ids[0]
            return BaseResult(
                error=(
                    f"Dataframe ID {only_id} was not found. "
                    "Use dataframes_list to discover available dataframes."
                )
            )

        info_messages = [
            f"Requested removal for {len(unique_ids)} dataframe(s). "
            f"Removed: {removed_count}. Missing: {len(missing_ids)}."
        ]
        if removed_count > 0:
            info_messages.append("Removed dataframes were unregistered from SQL context.")
        if missing_ids:
            info_messages.append(
                "Some dataframe IDs were not found: " + ", ".join(missing_ids) + "."
            )
        return BaseResult(
            result=removed_results,
            total=len(removed_results),
            has_more=False,
            info=info_messages,
        )

    @run_as_task()
    async def dataframes_clear(self) -> BaseResult:
        removed_count = await clear_dataframes(
            session_storage=self.session_storage,
            scope=self._scope(),
        )
        return BaseResult(
            result=[{"removed_count": removed_count, "remaining": 0}],
            info=[
                "All session dataframes were removed and unregistered from SQL context."
            ],
        )

    async def dataframes_sql_help(self) -> BaseResult:
        return BaseResult(
            result=[get_sql_capabilities()],
            info=["Only read-only SQL is allowed in dataframe queries."],
        )

