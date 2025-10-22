import traceback
from typing import Optional, Any, Dict

import httpx
from mcp.server.fastmcp import Context
from pydantic import Field

from config import perfecto
from config.perfecto import TOOLS_PREFIX, SUPPORT_MESSAGE
from config.token import PerfectoToken, token_verify
from formatters.device import format_real_device, format_virtual_device
from formatters.grid import format_grid_info
from models.manager import Manager
from models.result import BaseResult
from tools.utils import api_request


class DeviceManager(Manager):
    def __init__(self, token: Optional[PerfectoToken], ctx: Context):
        super().__init__(token, ctx)

    @token_verify
    async def read_selenium_grid_info(self) -> BaseResult:
        tenant_url = perfecto.get_tenant_management_api_url(self.token.cloud_name)
        tenant_response = await api_request(self.token, "GET", endpoint=tenant_url, result_formatter=format_grid_info)

        if tenant_response.error is None:
            selenium_grid_url = tenant_response.result[0].selenium_grid_url
            # Expand the Selenium Grid Status
            selenium_grid_status_response = await api_request(self.token, "GET", endpoint=f"{selenium_grid_url}/status")
            tenant_response.result[0].selenium_grid_status = selenium_grid_status_response.result

        return tenant_response

    @token_verify
    async def list_real_devices(self) -> BaseResult:
        devices_url = perfecto.get_real_device_management_api_url(self.token.cloud_name)
        # List all devices
        body = {
            "device": {
            }
        }
        return await api_request(self.token, "POST", endpoint=devices_url, json=body,
                                 result_formatter=format_real_device)

    @token_verify
    async def read_real_device_info(self, device_id: str) -> BaseResult:
        devices_url = perfecto.get_real_device_management_api_url(self.token.cloud_name)
        devices_url = f"{devices_url}/{device_id}"
        # TODO: Create a custom formatter for detailed information
        return await api_request(self.token, "GET", endpoint=devices_url)

    @token_verify
    async def list_virtual_devices(self) -> BaseResult:
        virtual_device_url = perfecto.get_virtual_device_management_api_url(self.token.cloud_name)
        return await api_request(self.token, "GET", endpoint=virtual_device_url, result_formatter=format_virtual_device)

    @token_verify
    async def list_desktop_devices(self) -> BaseResult:
        virtual_web_url = perfecto.get_web_desktop_management_api_url(self.token.cloud_name)
        return await api_request(self.token, "GET", endpoint=virtual_web_url)


def register(mcp, token: Optional[PerfectoToken]):
    @mcp.tool(
        name=f"{TOOLS_PREFIX}_devices",
        description="""
Operations on Perfecto devices information.
Actions:
- read_selenium_grid_info: Read the main Selenium Grid information like the Selenium Grid URL (for Selenium or Appium).
- list_real_devices: List all real available devices (iOS and Android devices, Mobile and Tablet).
- read_real_device_info: Read the real device information.
    args(dict): Dictionary with the following required parameters:
        device_id (str): The device Id to show detailed information.
- list_virtual_devices: List all available virtual devices (iOS Simulators and Android Emulators).
- list_desktop_devices: List all desktop browser devices (Desktop Web Browsers).
"""
    )
    async def devices(
            action: str = Field(description="The action id to execute"),
            args: Dict[str, Any] = Field(description="Dictionary with parameters"),
            ctx: Context = Field(description="Context object providing access to MCP capabilities")
    ) -> BaseResult:

        device_manager = DeviceManager(token, ctx)
        try:
            match action:
                case "read_selenium_grid_info":
                    return await device_manager.read_selenium_grid_info()
                case "list_real_devices":
                    return await device_manager.list_real_devices()
                case "read_real_device_info":
                    return await device_manager.read_real_device_info(args["device_id"])
                case "list_virtual_devices":
                    return await device_manager.list_virtual_devices()
                case "list_desktop_devices":
                    return await device_manager.list_desktop_devices()
                case _:
                    return BaseResult(
                        error=f"Action {action} not found in device manager tool"
                    )
        except httpx.HTTPStatusError:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}"
            )
        except Exception:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}\n{SUPPORT_MESSAGE}"
            )
