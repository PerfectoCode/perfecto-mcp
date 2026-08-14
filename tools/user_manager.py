from typing import Optional, Any, Dict

import httpx
from mcp.server.fastmcp import Context
from pydantic import Field

from config import perfecto
from config.perfecto import TOOLS_PREFIX, SUPPORT_MESSAGE, get_cloud_app_url
from config.token import PerfectoToken, token_verify
from formatters.user import format_users
from models.manager import Manager
from models.result import BaseResult
from telemetry import run_tool
from tools.utils import api_request, format_sanitized_traceback, normalize_action_args

class UserManager(Manager):
    def __init__(self, token: Optional[PerfectoToken], ctx: Context):
        super().__init__(token, ctx)

    @token_verify
    async def read_user(self) -> BaseResult:
        user_url = perfecto.get_user_management_api_url(self.token.cloud_name)
        user_url = user_url + "/current"
        cloud_url = get_cloud_app_url(self.token.cloud_name)
        result = await api_request(
            self.token,
            "GET",
            endpoint=user_url,
            result_formatter=format_users,
            result_formatter_params={"cloud_name": self.token.cloud_name},
        )
        if not result.error:
            result.append_info([f"Connected Perfecto cloud: [{cloud_url}]({cloud_url})"])
        return result


def register(mcp, token: Optional[PerfectoToken]):
    @mcp.tool(
        name=f"{TOOLS_PREFIX}_user",
        description="""
Operations on user information.
Actions:
- read_user: Read the current user and connected Perfecto cloud environment (cloud_name, cloud_url from PERFECTO_CLOUD_NAME).
Hints:
- Always render cloud_url as a markdown link when presenting the environment to the user.
"""
    )
    async def user(
            arguments: Dict[str, Any] = Field(description="Dictionary with arguments", default=None),
            ctx: Context = Field(description="Context object providing access to MCP capabilities")
    ) -> BaseResult:
        action, args = normalize_action_args(arguments)
        if args is None:
            args = {}
        user_manager = UserManager(token, ctx)

        async def _dispatch():
            match action:
                case "read_user":
                    return await user_manager.read_user()
                case _:
                    return BaseResult(
                        error=f"Action {action} not found in user manager tool"
                    )

        try:
            return await run_tool(f"{TOOLS_PREFIX}_user", action, ctx, _dispatch)
        except httpx.HTTPStatusError:
            return BaseResult(
                error=f"Error: {format_sanitized_traceback()}"
            )
        except Exception:
            return BaseResult(
                error=f"Error: {format_sanitized_traceback()}\n{SUPPORT_MESSAGE}"
            )
