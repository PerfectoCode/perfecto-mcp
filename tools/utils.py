"""
Simple utilities for Perfecto MCP tools.
"""
import base64
import os
import platform
import sys
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Optional, Callable

import httpx

from config.token import PerfectoToken
from config.version import __version__
from models.result import BaseResult

so = platform.system()  # "Windows", "Linux", "Darwin"
version = platform.version()  # kernel / build version
release = platform.release()  # ex. "10", "5.15.0-76-generic"
machine = platform.machine()  # ex. "x86_64", "AMD64", "arm64"

ua_part = f"{so} {release}; {machine}"
user_agent = f"perfecto-mcp/{__version__} ({ua_part})"
timeout = httpx.Timeout(
    connect=15.0,
    read=60.0,
    write=15.0,
    pool=60.0
)


async def api_request(token: Optional[PerfectoToken], method: str, endpoint: str,
                      result_formatter: Callable = None,
                      result_formatter_params: Optional[dict] = None,
                      **kwargs) -> BaseResult:
    """
    Make an authenticated request to the Perfecto API.
    Handles authentication errors gracefully.
    """
    if not token:
        return BaseResult(
            error="No API token. Set PERFECTO_SECURITY_TOKEN or PERFECTO_SECURITY_TOKEN_FILE env var with security token."
        )

    headers = kwargs.pop("headers", {})
    headers["Perfecto-Authorization"] = token.token
    headers["User-Agent"] = user_agent

    async with (httpx.AsyncClient(base_url="", http2=True, timeout=timeout) as client):
        try:
            resp = await client.request(method, endpoint, headers=headers, **kwargs)
            resp.raise_for_status()
            result = resp.json()
            error = None
            if isinstance(result, list) and len(result) > 0 and "userMessage" in result[0]:  # It's an error
                final_result = None
                error = result[0].get("userMessage", None)
            else:
                final_result = result_formatter(result, result_formatter_params) if result_formatter else result
            return BaseResult(
                result=final_result,
                error=error,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code in [401, 403]:
                return BaseResult(
                    error="Invalid credentials"
                )
            raise


async def http_request(method: str, endpoint: str,
                       result_formatter: Callable = None,
                       result_formatter_params: Optional[dict] = None,
                       **kwargs) -> BaseResult:
    """
    Make an http request to the Perfecto Webpage.
    """

    headers = kwargs.pop("headers", {})
    headers["User-Agent"] = user_agent

    async with (httpx.AsyncClient(base_url="", http2=True, timeout=timeout) as client):
        try:
            resp = await client.request(method, endpoint, headers=headers, **kwargs)
            resp.raise_for_status()
            result = resp.text
            error = None
            final_result = result_formatter(result, result_formatter_params) if result_formatter else result
            return BaseResult(
                result=final_result,
                error=error,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code in [401, 403]:
                return BaseResult(
                    error="Invalid credentials"
                )
            raise


def get_date_time_iso(timestamp: int) -> Optional[str]:
    if timestamp is None:
        return None
    else:
        return datetime.fromtimestamp(timestamp).isoformat()


def get_resources_path():
    try:
        resources_path = resources.files("resources")
    except ModuleNotFoundError:
        # Fallback for development or if not installed as package
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        resources_path = Path(base_path) / 'resources'
    return resources_path


def get_mcp_icon_uri():
    name = "app.png"
    icon_path = get_resources_path().joinpath(name)
    icon_data = base64.standard_b64encode(icon_path.read_bytes()).decode()
    return f"data:image/png;base64,{icon_data}"
