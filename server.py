from config.runtime import AppRuntime
from tools.ai_scriptless_manager import register as register_ai_scriptless_manager
from tools.device_manager import register as register_device_manager
from tools.execution_manager import register as register_execution_manager
from tools.help_manager import register as register_help_manager
from tools.tools_manager import register as register_tools_manager
from tools.user_manager import register as register_user_manager


def register_tools(mcp, runtime: AppRuntime):
    """
    Register all available tools with the MCP server.

    Args:
        mcp: The MCP server instance
        runtime: App runtime (transport + auth port and shared collaborators)
    """
    register_user_manager(mcp, runtime)
    register_device_manager(mcp, runtime)
    register_execution_manager(mcp, runtime)
    register_help_manager(mcp, runtime)
    register_ai_scriptless_manager(mcp, runtime)
    register_tools_manager(mcp, runtime)
