import traceback
from datetime import datetime, timedelta
from typing import Optional, Any, Dict

import httpx
from mcp.server.fastmcp import Context
from pydantic import Field

from config import perfecto
from config.perfecto import TOOLS_PREFIX, SUPPORT_MESSAGE
from config.token import PerfectoToken, token_verify
from formatters.execution import format_executions
from models.result import BaseResult, PaginationResult
from tools.utils import api_request


class ExecutionManager:
    def __init__(self, token: Optional[PerfectoToken], ctx: Context):
        self.token = token
        self.metadata_map = {
            "tag_list": "tags_v2",
            "device_id_list": "devices_v2",
            "job_name_list": "ciJobNames",
            "os_list": "os",
            "browser_list": "browsers",
            "platform_list": "deviceType",
            "failure_reason_list": "failureReasons",
            "job_number_list": "job_v2",
            "trigger_list": "triggerTypes",
            "owner_list": "owners_v2",
            "os_version_list": "os_info_v2"
        }
        self.metadata_in_root = [
            "failureReasons"
        ]
        self.filter_map = {
            "tag_list": "tags",
            "device_id_list": "deviceId",
            "job_name_list": "jobName",
            "os_list": "os",
            "browser_list": "browserType",
            "platform_list": "deviceType",
            "failure_reason_list": "failureReason",
            "job_number_list": "jobNumber",
            "trigger_list": "triggerType",
            "owner_list": "owner",
            "os_version_list": "osVersion"
        }

    @token_verify
    async def list_live_executions(self) -> BaseResult:
        execution_management_url = perfecto.get_execution_management_api_url(self.token.cloud_name)
        execution_management_url = execution_management_url + "/search"
        return await api_request(self.token, "POST", endpoint=execution_management_url)

    @token_verify
    async def stop_live_executions(self, execution_id_list: list[str]) -> BaseResult:
        execution_management_url = perfecto.get_execution_management_api_url(self.token.cloud_name)
        execution_management_url = execution_management_url + "/stop"

        if execution_id_list:
            # Stop specific id
            body = {
                "fields": {
                    "id": execution_id_list,
                },
            }
            # TODO: Create a custom formatter for detailed information
            return await api_request(self.token, "POST", endpoint=execution_management_url, json=body)
        else:
            return BaseResult(
                warning=["No list of execution IDs to be stopped was indicated."]
            )

    @token_verify
    async def list_report_names(self) -> BaseResult:
        report_management_url = perfecto.get_test_execution_name_api_url(self.token.cloud_name)
        body = {}
        # TODO: Create a custom formatter for detailed information
        return await api_request(self.token, "POST", endpoint=report_management_url, json=body)

    @token_verify
    async def list_filter_values(self, filter_names: list[str]) -> BaseResult:
        metadata_management_url = perfecto.get_test_execution_metadata_api_url(self.token.cloud_name)

        metadata_result = await api_request(self.token, "GET", endpoint=metadata_management_url)
        metadata = metadata_result.result
        filter_values = {}
        for filter_name in filter_names:
            if self.metadata_map[filter_name] in self.metadata_in_root:
                if filter_name in self.metadata_map and self.metadata_map[filter_name] in metadata:
                    filter_values[filter_name] = metadata[self.metadata_map[filter_name]]
            else:
                if filter_name in self.metadata_map and self.metadata_map[filter_name] in metadata["items"]:
                    filter_values[filter_name] = metadata["items"][self.metadata_map[filter_name]]["values"]

        # TODO: Evaluate if it's needed a custom formatter for some metadata values
        return BaseResult(
            result=filter_values,
        )

    @token_verify
    async def list_report_executions(self, args: dict[str, Any]) -> BaseResult:
        page_size = 50
        page_index = args.get("page_index", 1)
        skip = (page_size * page_index) - page_size
        report_name = args.get("report_name", "")
        time_frame = args.get("time_frame", "latest")
        start_time_str = args.get("start_time", "")
        end_time_str = args.get("end_time", "")

        start_time_dt = datetime.now()
        if time_frame == "latest":
            start_time_dt = start_time_dt - timedelta(days=0)
        elif time_frame == "last24":
            start_time_dt = start_time_dt - timedelta(days=1)
        elif time_frame == "lastWeek":
            start_time_dt = start_time_dt - timedelta(days=7)
        elif time_frame == "lastMonth":
            start_time_dt = start_time_dt - timedelta(days=30)
        elif time_frame == "custom":
            start_time_dt = datetime.fromisoformat(start_time_str)
        start_time_dt = start_time_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        start_time = int(start_time_dt.timestamp() * 1000)
        end_time = start_time
        if time_frame == "custom":
            end_time_dt = datetime.fromisoformat(end_time_str)
            end_time_dt = end_time_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = int(end_time_dt.timestamp() * 1000)

        report_management_url = perfecto.get_test_execution_management_api_url(self.token.cloud_name)
        report_management_url = report_management_url + "/search"

        body = {
            "filter": {
                "fieldNameToSearchFilter": {
                    "name": {
                        "term": f"{report_name}", "exact": False
                    }
                },
                "fields": {
                    "startExecutionTime": [start_time]
                },
                "excludedFields": {}
            },
            "sort": [
                {
                    "sortBy": "startTime",
                    "sortOrder": "DESCEND"
                }
            ],
            "skip": skip,
            "pageSize": page_size
        }
        if time_frame == "custom":
            body["filter"]["fields"]["endExecutionTime"] = [end_time]

        for filter_arg, target in self.filter_map.items():
            filter_values = args.get(filter_arg, [])
            if len(filter_values) > 0:
                body["filter"]["fields"][target] = filter_values

        executions = await api_request(self.token, "POST", endpoint=report_management_url, json=body,
                                       result_formatter=format_executions,
                                       result_formatter_params={"cloud_name": self.token.cloud_name})

        page_result = PaginationResult(
            items=executions.result,
            count=len(executions.result),
            page=page_index,
            offset=skip,
            next_offset=skip + page_size,
            has_more=page_size - len(executions.result) <= 0,
        )

        return BaseResult(
            result=page_result,
            error=executions.error,
            warning=executions.warning,
            info=executions.info,
        )


def register(mcp, token: Optional[PerfectoToken]):
    @mcp.tool(
        name=f"{TOOLS_PREFIX}_execution",
        description="""
Operations on execution information.
Actions:
- list_live_executions: List all live executions (Mobile, Tablet and Desktop Browser).
- stop_live_executions: Stop live executions.
    args(dict): Dictionary with the following required parameters:
        execution_id_list (list[str]): The execution Id to to be stopped.
- list_report_names: List alls report names.
- list_report_executions: List finished executions.
    args(dict): Dictionary with the following optional filter parameters:
        report_name (str): The report name.
        time_frame (str, default='latest', values['latest','last24','lastWeek','lastMonth', 'custom']): 
            The time frame to filter the execution results. 
            latest=Today, last24=Last 24 hours, lastWeek=Last 7 days, lastMonth=Last 30 days, custom= Custom Filter Range (use start_time and end_time).
        start_time (str): The start time in ISO format (only when time_frame is 'custom').
        end_time (str): The end time in ISO format (only when time_frame is 'custom').
        device_id_list (list[str], values= use first list_filter_values tool with 'device_id_list'): The real device IDs to filter the execution results.
        os_list (list[str], values= use first list_filter_values tool with 'os_list'): The list of OS IDs to filter the execution results.
        platform_list (list[str], values= use first list_filter_values tool with 'platform_list'): The list of platform type to filter the execution results.
        browser_list (list[str], values= use first list_filter_values tool with 'browser_list'): The list of browsers to filter the execution results.
        job_name_list (list[str], values= use first list_filter_values tool with 'job_name_list'): The list of job names to filter the execution results.
        trigger_list (list[str], values= use first list_filter_values tool with 'trigger_list'): The list of trigger types to filter the execution results.
        tag_list (list[str], values= use first list_filter_values tool with 'tag_list'): The list of tags to filter the execution results.
        owner_list (list[str], values= use first list_filter_values tool with 'owner_list'): The list of owners to filter the execution results.
        os_version_list (list[str], values= use first list_filter_values tool with 'os_version_list'): The list of operating system versions to filter the execution results.
        failure_reason_list (list[str], values= use first list_filter_values tool with 'failure_reason_list'): The list of failure reason IDs to filter the execution results.
        page_index (int, default=1), The current page number. If the result mention has_next_page in true, asks the user if they want to see the next page. 
        
- list_filter_values: List the values needed for list_report_executions filters
    args(dict): Dictionary with the following required filter parameters:
        filter_names (list[str], values=['device_id_list', 'os_list', 'browser_list']): The filter name list.
Hints:
- IMPORTANT: Always call list_filter_values first to get valid filter values before using any filters in list_report_executions. 
  This ensures you're using the correct device IDs, test names, or other filter values that actually exist in the execution reports system.
- The device IDs from list_real_devices may not match the device IDs used in execution reports. Use list_filter_values to get the exact device IDs that are valid for filtering executions.
- When filtering by device_id_list, time_frame, or test_name, always verify the valid values using list_filter_values to avoid empty results due to incorrect filter values.
- Always generates the url attributes as a link in markdown format (like execution_url). 
"""
    )
    async def execution(
            action: str = Field(description="The action id to execute"),
            args: Dict[str, Any] = Field(description="Dictionary with parameters"),
            ctx: Context = Field(description="Context object providing access to MCP capabilities")
    ) -> BaseResult:

        execution_manager = ExecutionManager(token, ctx)
        try:
            match action:
                case "list_live_executions":
                    return await execution_manager.list_live_executions()
                case "stop_live_executions":
                    return await execution_manager.stop_live_executions(args["execution_id_list"])
                case "list_report_names":
                    return await execution_manager.list_report_names()
                case "list_report_executions":
                    return await execution_manager.list_report_executions(args)
                case "list_filter_values":
                    return await execution_manager.list_filter_values(args.get("filter_names", []))
                case _:
                    return BaseResult(
                        error=f"Action {action} not found in execution manager tool"
                    )
        except httpx.HTTPStatusError:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}"
            )
        except Exception:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}\n{SUPPORT_MESSAGE}"
            )
