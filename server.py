from typing import Optional

from config.token import PerfectoToken
from tools.ai_scriptless_mobile_manager import register as register_ai_scriptless_mobile_manager
from tools.device_manager import register as register_device_manager
from tools.execution_manager import register as register_execution_manager
from tools.help_manager import register as register_help_manager
from tools.user_manager import register as register_user_manager


def register_tools(mcp, token: Optional[PerfectoToken]):
    """
    Register all available tools with the MCP server.

    Args:
        mcp: The MCP server instance
        token: Optional Perfecto token (can be None if not configured)
    """
    register_user_manager(mcp, token)
    register_device_manager(mcp, token)
    register_execution_manager(mcp, token)
    register_help_manager(mcp, token)
    register_ai_scriptless_mobile_manager(mcp, token)
