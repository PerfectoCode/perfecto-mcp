"""
Simple utilities for Perfecto MCP tools.
"""
import base64
import json
import os
import platform
import re
import sys
import traceback
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Optional, Callable, Any, Dict

import httpx

from config.security import validate_http_request_endpoint
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
project_root = Path(__file__).resolve().parent.parent
# Match Windows absolute paths (backslash or forward slash; latter may appear on POSIX).
# Negative lookbehind ensures we don't match URL protocols like https:// (where the
# letter before ':' is preceded by more letters, e.g. 'http' in 'https://').
windows_abs_path_pattern = re.compile(
    r"(?<![A-Za-z])[A-Za-z]:[\\/](?:[^\\\n\r\t\"']+[\\/])*[^\\\n\r\t\"']*"
)
unix_abs_path_pattern = re.compile(
    r"/(?:"
    r"Users|home|root"  # User home directories (macOS, Linux)
    r"|var|tmp|etc|opt|srv"  # Standard Linux directories
    r"|mnt|run|media"  # Mount points and runtime (Linux)
    r"|app|data"  # Common Docker container directories
    r"|System|Library|Applications|private|Volumes"  # macOS directories
    r")/[^\n\r\t\"']+"
)


def sanitize_path(path_value: str) -> str:
    if not path_value:
        return path_value

    # On POSIX, Windows-style paths (e.g. from compile() or cross-platform code)
    # resolve to cwd+path, so relative_to() would incorrectly return the raw path.
    # Redact them immediately. On Windows, the normal flow handles them correctly.
    if so != "Windows" and re.match(r"^[A-Za-z]:[\\/]", path_value):
        return Path(path_value.replace("\\", "/")).name or "<root hidden>"

    try:
        absolute_path = Path(path_value).resolve()
        relative_path = absolute_path.relative_to(project_root)
        return relative_path.as_posix()
    except Exception:
        pass

    if re.match(r"^[A-Za-z]:[\\/]", path_value) or path_value.startswith("/"):
        return Path(path_value.replace("\\", "/")).name or "<root hidden>"

    return path_value


def redact_system_paths(text: str) -> str:
    def replace_match(match: re.Match) -> str:
        return sanitize_path(match.group(0))

    text = windows_abs_path_pattern.sub(replace_match, text)
    text = unix_abs_path_pattern.sub(replace_match, text)
    return text


def _sanitize_traceback_exception(tb_exception: traceback.TracebackException):
    for frame in tb_exception.stack:
        frame.filename = sanitize_path(frame.filename)

    if tb_exception.__cause__:
        _sanitize_traceback_exception(tb_exception.__cause__)
    if tb_exception.__context__ and not tb_exception.__suppress_context__:
        _sanitize_traceback_exception(tb_exception.__context__)


def format_sanitized_traceback(exc: Optional[BaseException] = None) -> str:
    if exc is None:
        exc = sys.exc_info()[1]

    if exc is None:
        return "No traceback available."

    tb_exception = traceback.TracebackException.from_exception(exc, capture_locals=False)
    _sanitize_traceback_exception(tb_exception)
    formatted_traceback = "".join(tb_exception.format()).strip()
    return redact_system_paths(formatted_traceback)


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
            if not resp.content or not resp.content.strip():
                result = None
            else:
                try:
                    result = resp.json()
                except json.JSONDecodeError:
                    result = resp.text
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

    endpoint_error = validate_http_request_endpoint(endpoint)
    if endpoint_error:
        return BaseResult(error=endpoint_error)

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
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


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

def normalize_action_args(arguments: Optional[Dict[str, Any]] = None) -> tuple[str, Dict[str, Any]]:
    """
    Normalize tool arguments to (action, args) format.
    Supports:
      - {"action": "x", "args": {"key": "value"}}
      - {"action": "x", "key": "value"}  (params at top level, merged into args)
      - {"arguments": {"action": "x", "args": {...}}}  (double-wrapped by client)
    Top-level keys other than 'action' and 'args' are merged into args.
    Use a single 'arguments' param so the full MCP tool call payload is received
    (avoids Pydantic dropping extra fields when using action/args separately).
    """
    arguments = arguments or {}
    # Unwrap double-nested format: {"arguments": {"action": "x", "args": {...}}}
    inner = arguments.get("arguments")
    if (
            isinstance(inner, dict)
            and len(arguments) == 1
            and ("action" in inner or "args" in inner)
    ):
        arguments = inner
    action = str(arguments.get("action") or "").strip() or ""
    args = dict(arguments.get("args") or {})
    for key, value in arguments.items():
        if key not in ("action", "args"):
            args[key] = value
    return action, args

