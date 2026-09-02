from mcp.server.fastmcp import Context

from config.context_resolution import resolve_ctx_token


class Manager:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.token = resolve_ctx_token(ctx)
