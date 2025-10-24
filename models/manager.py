from typing import Optional

from mcp.server.fastmcp import Context

from config.token import PerfectoToken


class Manager:
    def __init__(self, token: Optional[PerfectoToken], ctx: Context):
        self.token = token
        self.ctx = ctx
