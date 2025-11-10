import traceback
from typing import Optional, Any, Dict

import httpx
from mcp.server.fastmcp import Context
from pydantic import Field

from config import perfecto
from config.perfecto import TOOLS_PREFIX, SUPPORT_MESSAGE
from config.token import PerfectoToken, token_verify
from formatters.ai_scriptless_mobile import format_ai_scriptless_mobile_tests, \
    format_ai_scriptless_mobile_tests_filter_values
from models.manager import Manager
from models.result import BaseResult, PaginationResult
from tools.utils import api_request


class AiScriptlessMobileManager(Manager):
    def __init__(self, token: Optional[PerfectoToken], ctx: Context):
        super().__init__(token, ctx)

    @token_verify
    async def list_tests(self, args: dict[str, Any]) -> BaseResult:
        page_size = 50
        page_index = args.get("page_index", 1)
        skip = (page_size * page_index) - page_size

        tree_url = perfecto.get_ai_scriptless_mobile_api_url(self.token.cloud_name)
        tree_url = tree_url + "/scripts/tree"
        tests_result = await api_request(self.token, "GET", endpoint=tree_url,
                                         result_formatter=format_ai_scriptless_mobile_tests,
                                         result_formatter_params={"page_size": page_size, "skip": skip,
                                                                  "filters": args})

        page_result = PaginationResult(
            items=tests_result.result,
            count=len(tests_result.result),
            page=page_index,
            offset=skip,
            next_offset=skip + page_size,
            has_more=page_size - len(tests_result.result) <= 0,
        )

        return BaseResult(
            result=page_result,
            error=tests_result.error,
            warning=tests_result.warning,
            info=tests_result.info,
        )

    @token_verify
    async def list_filter_values(self, filter_names: list[str]) -> BaseResult:
        tree_url = perfecto.get_ai_scriptless_mobile_api_url(self.token.cloud_name)
        tree_url = tree_url + "/scripts/tree"
        filter_values_result = await api_request(self.token, "GET", endpoint=tree_url,
                                          result_formatter=format_ai_scriptless_mobile_tests_filter_values)
        filter_values = {}
        for filter_name in filter_names:
            filter_values[filter_name] = filter_values_result.result[filter_name]

        return BaseResult(
            result=filter_values,
        )

    @token_verify
    async def execute_test(self, test_id:str, device_id: str) -> BaseResult:
        execute_url = perfecto.get_ai_scriptless_mobile_execution_api_url(self.token.cloud_name)

        body= {
            "params": {
                "DUT": device_id
            },
            "testKey": test_id,
            "triggerType": "Manual"
        }
        return await api_request(self.token, "POST", endpoint=execute_url, json=body)


def register(mcp, token: Optional[PerfectoToken]):
    @mcp.tool(
        name=f"{TOOLS_PREFIX}_ai_scriptless_mobile",
        description="""
Operations on AI Scriptless information.
Actions:
- list_tests: List all available AI Scriptless Mobile Test from Perfecto.
    args(dict): Dictionary with the following optional filter parameters:
        test_name (str): The test name to filter.
        visibility (str, default='PRIVATE' values=['PUBLIC', 'PRIVATE']): The visibility, PUBLIC=All Public Tests, PRIVATE=My private tests.
        owner_list (list[str], values= use first list_filter_values tool with 'owner_list'): The list of users to filter tests (owners).
        page_index (int, default=1), The current page number. If the result mention has_next_page in true, asks the user if they want to see the next page.
- list_filter_values: List the values needed for list_report_executions filters
    args(dict): Dictionary with the following required filter parameters:
        filter_names (list[str], values=['test_name', 'owner_list']): The filter name list.
- execute_test: Execute a preconfigured AI Scriptless Mobile Test, you need to know the test_id of a created and configured test and the real device_id available an not in use to run the test.
    args(dict): Dictionary with the following required parameters:
        test_id (str): The test Id that should be started.
        device_id (str): The real device Id to run the test.
Hints:
- IMPORTANT: Always call list_filter_values first to get valid filter values before using any filters in list_tests. 
  This ensures you're using the correct test name, list of owners users or other filter values that actually exist in the system.
- Always check before running a test_id if the device (device_id) is available, not in use or malfunctioning.
- Always monitor a device's operation while it's in use by checking the live executions.
- Always stop the execution by stopping the live execution (make sure it's the correct execution, such as the execution name or user ID).
"""
    )
    async def ai_scriptless_mobile(
            action: str = Field(description="The action id to execute"),
            args: Dict[str, Any] = Field(description="Dictionary with parameters", default=None),
            ctx: Context = Field(description="Context object providing access to MCP capabilities")
    ) -> BaseResult:
        if args is None:
            args = {}
        ai_scriptless_mobile_manager = AiScriptlessMobileManager(token, ctx)
        try:
            match action:
                case "list_tests":
                    return await ai_scriptless_mobile_manager.list_tests(args)
                case "list_filter_values":
                    return await ai_scriptless_mobile_manager.list_filter_values(args.get("filter_names",[]))
                case "execute_test":
                    return await ai_scriptless_mobile_manager.execute_test(args.get("test_id", ""), args.get("device_id", ""))
                case _:
                    return BaseResult(
                        error=f"Action {action} not found in AI Scriptless Mobile manager tool"
                    )
        except httpx.HTTPStatusError:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}"
            )
        except Exception:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}\n{SUPPORT_MESSAGE}"
            )
