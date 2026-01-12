import json
import traceback
from typing import Optional, Any, Dict

import httpx
from mcp.server.fastmcp import Context
from pydantic import Field

from config import perfecto
from config.perfecto import TOOLS_PREFIX, SUPPORT_MESSAGE
from config.token import PerfectoToken, token_verify
from formatters.ai_scriptless import format_ai_scriptless_tests, \
    format_ai_scriptless_tests_filter_values
from models.manager import Manager
from models.result import BaseResult, PaginationResult
from tools.utils import api_request


class AiScriptlessManager(Manager):
    def __init__(self, token: Optional[PerfectoToken], ctx: Context):
        super().__init__(token, ctx)

    @token_verify
    async def list_tests(self, args: dict[str, Any]) -> BaseResult:
        page_size = 50
        page_index = args.get("page_index", 1)
        skip = (page_size * page_index) - page_size

        tree_url = perfecto.get_ai_scriptless_api_url(self.token.cloud_name)
        tree_url = tree_url + "/scripts/tree"
        tests_result = await api_request(self.token, "GET", endpoint=tree_url,
                                         result_formatter=format_ai_scriptless_tests,
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
        tree_url = perfecto.get_ai_scriptless_api_url(self.token.cloud_name)
        tree_url = tree_url + "/scripts/tree"
        filter_values_result = await api_request(self.token, "GET", endpoint=tree_url,
                                                 result_formatter=format_ai_scriptless_tests_filter_values)
        filter_values = {}
        filter_not_found = []
        for filter_name in filter_names:
            if filter_name in filter_values_result.result:
                filter_values[filter_name] = filter_values_result.result[filter_name]
            else:
                filter_not_found.append(filter_name)

        error = None
        warnings = None
        if len(filter_not_found) > 0:
            error = f"Error, invalid filter_names values: {','.join(filter_not_found)}"
            warnings = [f"Make sure to use valid filter_names values: {','.join(['test_name', 'owner_list'])}"]

        return BaseResult(
            result=filter_values,
            error=error,
            warning=warnings,
        )

    @token_verify
    async def execute_test(self, test_id: str, device_type: str, device_under_test: dict[str, Any]) -> BaseResult:
        execute_url = perfecto.get_ai_scriptless_execution_api_url(self.token.cloud_name)

        # This mapping allows us to detect when the AI gets confused and uses Perfecto-style capabilities.
        # It also allows for reverse mapping from internal to capabilities from Perfecto.
        att_map = {
            "real": {
                "device_id": "deviceId"
            },
            "virtual": {
                "platform_name": "platformName",
                "manufacturer": "manufacturer",
                "model": "model",
                "platform_version": "platformVersion"
            },
            "desktop": {
                "platform_name": "platformName",
                "platform_version": "platformVersion",
                "browser_name": "browserName",
                "browser_version": "browserVersion",
                "resolution": "resolution",
                "location": "location"
            }
        }

        dut = None
        remapped_device_under_test = {}
        # Remap the attributes to Perfecto Capabilities format
        if device_type in att_map.keys():
            for key in att_map[device_type].keys():
                alt_key = att_map[device_type][key]
                remapped_device_under_test[alt_key] = device_under_test.get(key, device_under_test.get(alt_key, None))

        if device_type == "real":
            dut = remapped_device_under_test.get("deviceId", None)
            if dut is None:
                return BaseResult(
                    error="Invalid value for device_under_test. The key device_id could not be found."
                )
        elif device_type in ["virtual", "desktop"]:
            # Verify if all the needed keys exist on the remapped version
            key_not_found = []
            for key in att_map[device_type].keys():
                alt_key = att_map[device_type][key]
                if alt_key not in remapped_device_under_test:
                    key_not_found.append(key)
            if len(key_not_found) == 0:
                dut = json.dumps(remapped_device_under_test, separators=(',', ':'))
            else:
                keys_not_found_str = ",".join(key_not_found)
                return BaseResult(
                    error=f"Invalid value for device_under_test. The keys [{keys_not_found_str}] could not be found."
                )
        if dut is not None and len(dut) > 0:
            body = {
                "params": {
                    "DUT": dut
                },
                "testKey": test_id,
                "triggerType": "Manual"
            }
            return await api_request(self.token, "POST", endpoint=execute_url, json=body)
        else:
            return BaseResult(
                error="Invalid device_type or device_under_test value."
            )


def register(mcp, token: Optional[PerfectoToken]):
    @mcp.tool(
        name=f"{TOOLS_PREFIX}_ai_scriptless",
        description="""
Operations on AI Scriptless information.
Actions:
- list_tests: List all available AI Scriptless Test from Perfecto.
    args(dict): Dictionary with the following optional filter parameters:
        test_name (str): The test name to filter.
        visibility (str, default='PRIVATE' values=['PUBLIC', 'PRIVATE']): The visibility, PUBLIC=All Public Tests, PRIVATE=My private tests.
        owner_list (list[str], values= use first list_filter_values tool with 'owner_list'): The list of users to filter tests (owners).
        page_index (int, default=1), The current page number. If the result mention has_next_page in true, asks the user if they want to see the next page.
- list_filter_values: List the values needed for list_tests filters.
    args(dict): Dictionary with the following required filter parameters:
        filter_names (list[str], values=['test_name', 'owner_list']): The filter name list.
- execute_test: Execute a preconfigured AI Scriptless Test.
    args(dict): Dictionary with the following required parameters:
        test_id (str): Test ID from list_tests()
        device_type (str, default='real', values=['real', 'virtual', 'desktop']: The device type. 
        device_under_test (dict, required): Device configuration object.
            When device_type='real': {device_id: str} (Get from list_real_devices()).
            When device_type='virtual': {platform_name: str, manufacturer: str, model: str, platform_version: str} (Get from list_virtual_devices()).
            When device_type='desktop': {platform_name: str, platform_version: str, browser_name: str, 
                          browser_version: str, resolution: str, location: str} (Get from list_desktop_devices()).
Hints:
- IMPORTANT: Always call list_filter_values first to get valid filter values before using any filters in list_tests. 
  This ensures you're using the correct test name, list of owners users or other filter values that actually exist in the system.
- If in any result has_next_page is true, ask the user if they want to see the next page or access all pages before making a subsequent call.
- Before executing a test, follow this validation workflow:
  1. list_tests() (get and validate test_id).
  2. Get device configuration based on device_type:
     - 'real': list_real_devices() (get device_id).
     - 'virtual': list_virtual_devices() (get platform_name, manufacturer, model, platform_version).
     - 'desktop': list_desktop_devices() (get platform_name, platform_version, browser_name, browser_version, resolution, location).
  3. On real device use read_real_device_info() (verify device is available and not in use).
  4. execute_test() (execute the test).
  5. list_report_executions() with report name equal to test name and list_live_executions() when the device it's in use (monitor execution progress).
- Always check before running a test_id if the device_type and device_under_test exist and is available (when it's a real device), not use device in use or malfunctioning.
- Always monitor a real device's operation while it's in use by checking the information with read_real_device_info().
- Always stop the execution by stopping the live execution (make sure it's the correct execution, such as the execution name or user ID).
"""
    )
    async def ai_scriptless(
            action: str = Field(description="The action id to execute"),
            args: Dict[str, Any] = Field(description="Dictionary with parameters", default=None),
            ctx: Context = Field(description="Context object providing access to MCP capabilities")
    ) -> BaseResult:
        if args is None:
            args = {}
        ai_scriptless_manager = AiScriptlessManager(token, ctx)
        try:
            match action:
                case "list_tests":
                    return await ai_scriptless_manager.list_tests(args)
                case "list_filter_values":
                    return await ai_scriptless_manager.list_filter_values(args.get("filter_names", []))
                case "execute_test":
                    return await ai_scriptless_manager.execute_test(args.get("test_id", ""),
                                                                    args.get("device_type", ""),
                                                                    args.get("device_under_test", {}))
                case _:
                    return BaseResult(
                        error=f"Action {action} not found in AI Scriptless manager tool"
                    )
        except httpx.HTTPStatusError:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}"
            )
        except Exception:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}\n{SUPPORT_MESSAGE}"
            )
