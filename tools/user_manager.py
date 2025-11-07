import traceback
from typing import Optional, Any, Dict

import httpx
from mcp.server.fastmcp import Context
from pydantic import Field

from config import perfecto
from config.perfecto import TOOLS_PREFIX, SUPPORT_MESSAGE
from config.token import PerfectoToken, token_verify
from formatters.user import format_users
from models.manager import Manager
from models.result import BaseResult
from tools.utils import api_request


class UserManager(Manager):
    def __init__(self, token: Optional[PerfectoToken], ctx: Context):
        super().__init__(token, ctx)

    @token_verify
    async def read_user(self) -> BaseResult:
        user_url = perfecto.get_user_management_api_url(self.token.cloud_name)
        user_url = user_url + "/current"
        return await api_request(self.token, "GET", endpoint=user_url, result_formatter=format_users)


def register(mcp, token: Optional[PerfectoToken]):
    @mcp.tool(
        name=f"{TOOLS_PREFIX}_user",
        description="""
Operations on user information.
Actions:
- read_user: Read a current user information from Perfecto.
"""
    )
    async def user(
            action: str = Field(description="The action id to execute"),
            args: Dict[str, Any] = Field(description="Dictionary with parameters", default=None),
            ctx: Context = Field(description="Context object providing access to MCP capabilities")
    ) -> BaseResult:
        if args is None:
            args = {}
        user_manager = UserManager(token, ctx)
        try:
            match action:
                case "read_user":
                    return await user_manager.read_user()
                case _:
                    return BaseResult(
                        error=f"Action {action} not found in user manager tool"
                    )
        except httpx.HTTPStatusError:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}"
            )
        except Exception:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}\n{SUPPORT_MESSAGE}"
            )
