"""Shared HTTP client defaults for Perfecto MCP (no dependency on tools.*)."""

import platform

import httpx

from config.version import __version__

_ua_part = f"{platform.system()} {platform.release()}; {platform.machine()}"
user_agent = f"perfecto-mcp/{__version__} ({_ua_part})"

timeout = httpx.Timeout(
    connect=15.0,
    read=60.0,
    write=15.0,
    pool=60.0,
)
