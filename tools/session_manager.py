"""Open a chat session for the Perfecto caller of the current tool call."""
import logging

from config.perfecto import TOOLS_PREFIX
from config.runtime import AppRuntime
from config.session import SESSION_TOOL_NAME, SessionError, SessionErrorCode
from config.session_context import SessionContextMissing, current_credential, current_identity
from models.result import BaseResult
from tools.runtime_tools import run_tool_with_runtime
from tools.utils import normalize_action_args

logger = logging.getLogger(__name__)

_HEADER = (
    "Chat session for this conversation. Call it ONCE at the start of the conversation, "
    "before any other Perfecto tool, and keep the returned session_id in context."
)


class SessionManager:
    def __init__(self, sessions):
        self.sessions = sessions

    async def get(self) -> BaseResult:
        identity = current_identity()
        credential = current_credential()
        if identity is None or not credential:
            raise SessionContextMissing("The caller identity was not bound for this call.")
        try:
            session = await self.sessions.open(identity.user_id, credential)
        except SessionError as exc:
            return BaseResult(error=exc.message, error_code=exc.code.value)
        except Exception:
            logger.exception("Opening a chat session failed")
            unavailable = SessionError(SessionErrorCode.UNAVAILABLE)
            return BaseResult(error=unavailable.message, error_code=unavailable.code.value)
        return BaseResult(
            result=[{
                "session_id": session.session_id,
                "state": session.state.value,
                "created_at": session.created_at.isoformat(),
            }],
            session_id=session.session_id,
            info=[
                "Keep this session_id in context and pass it as 'session_id' in every Perfecto "
                "tool call of this conversation. Do not call this tool again unless a tool returns "
                "SESSION_REQUIRED, SESSION_INVALID or SESSION_EXPIRED.",
            ],
        )


def register(mcp, runtime: AppRuntime):
    manager = SessionManager(runtime.sessions)

    @mcp.tool(
        name=SESSION_TOOL_NAME,
        description=f"""
{_HEADER}
Actions:
- get: Start a new chat session and return its session_id.
    args(dict): No arguments.
Hints:
- **CRITICAL**: Pass the returned `session_id` in every call to every other {TOOLS_PREFIX} tool
  of this conversation (next to action, or inside args). Do not call 'get' again while it keeps working.
- **CRITICAL**: Never reuse a session_id from another conversation: tasks and dataframes are
  isolated per session.
- Only call 'get' again when a tool returns error_code SESSION_REQUIRED, SESSION_INVALID or
  SESSION_EXPIRED; then use the new session_id and re-run the calls whose tasks or dataframes
  you still need.
""",
    )
    async def session_tool(arguments: dict = None, ctx=None) -> BaseResult:
        action, args = normalize_action_args(arguments)
        runtime.configure_context(ctx)

        async def _dispatch():
            match action:
                case "get":
                    return await manager.get()
                case _:
                    return BaseResult(error=f"Action {action} not found in session tool")

        return await run_tool_with_runtime(
            runtime,
            SESSION_TOOL_NAME,
            action,
            ctx,
            _dispatch,
            tool_args=args,
            requires_session=False,
            disable_dataframe_materialization=True,
        )
