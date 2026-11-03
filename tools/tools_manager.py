import os
import platform
import sys
import traceback
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import Context
from packaging.version import InvalidVersion, Version
from pydantic import Field

from config.perfecto import (
    GITHUB,
    GITHUB_API_LATEST_RELEASE,
    SUPPORT_MESSAGE,
    TOOLS_PREFIX,
    WEBSITE,
)
from config.runtime import AppRuntime
from config.version import __bundle__, __executable__, __uvx__, __version__
from models.manager import Manager
from models.result import BaseResult
from tools.call_state import TOOLS_ACTIONS_SKIP_AUTO_DATAFRAME
from tools.data_tools import DataTools
from tools.runtime_tools import run_tool_with_runtime
from tools.utils import (
    normalize_action_args,
    timeout,
    user_agent,
    validate_non_empty_str_arg,
    validate_required_args,
)


def _normalize_system(system: str) -> str:
    system = system.lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    return "linux"


def _normalize_arch(machine: str) -> str:
    machine = machine.lower()
    if machine in {"x86_64", "amd64"}:
        return "amd64"
    if machine in {"aarch64", "arm64"} or machine.startswith("arm"):
        return "arm64"
    return machine


def _parse_version(value: str) -> Optional[Version]:
    try:
        return Version(str(value).lstrip("vV"))
    except InvalidVersion:
        return None


def _detect_runtime() -> Dict[str, Any]:
    return {
        "frozen": bool(getattr(sys, "frozen", False)),
        "uvx": bool(__uvx__),
        "docker": os.getenv("MCP_DOCKER", "false").lower() == "true",
        "executable": __executable__,
        "bundle": __bundle__,
    }


def _platform_info() -> Dict[str, str]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "normalized_system": _normalize_system(platform.system()),
        "normalized_arch": _normalize_arch(platform.machine()),
    }


def _match_recommended_asset(assets: List[Dict[str, Any]], system: str, arch: str) -> Optional[Dict[str, Any]]:
    prefix = f"perfecto-mcp-{system}-{arch}"
    exact = [
        asset for asset in assets
        if str(asset.get("name", "")).startswith(prefix)
    ]
    if exact:
        # Prefer zip packages when multiple assets share the same platform prefix.
        zip_assets = [asset for asset in exact if str(asset.get("name", "")).endswith(".zip")]
        return zip_assets[0] if zip_assets else exact[0]
    return None


def _releases_url() -> str:
    return f"{GITHUB}/releases"


def _update_guidance(runtime: Dict[str, Any], update_available: bool, recommended_asset: Optional[Dict[str, Any]]) -> Dict[str, str]:
    releases_url = _releases_url()
    manual = (
        f"Download the package for your platform from {releases_url}, "
        "replace the current MCP executable with the new one, then restart the MCP client."
    )
    if recommended_asset and recommended_asset.get("browser_download_url"):
        manual = (
            f"Download [{recommended_asset['name']}]({recommended_asset['browser_download_url']}), "
            "replace the current MCP executable with the new one, then restart the MCP client."
        )

    if runtime.get("docker"):
        automatic = (
            "Pull the latest Docker image (`ghcr.io/perfectocode/perfecto-mcp:latest`) "
            "and restart the MCP container/client."
        )
    elif runtime.get("uvx"):
        automatic = (
            f"Update the MCP client config git ref to the latest release tag "
            f"(for example `git+{GITHUB}.git@v<latest_version>`) and restart the MCP client."
        )
    else:
        automatic = (
            "Automatic in-place update is not available yet. "
            "Use the manual download path above, or ask the AI to guide a controlled manual replace."
        )

    if not update_available:
        return {
            "status": "up_to_date",
            "manual": f"No update required. Releases are listed at {releases_url}.",
            "automatic": "No update required.",
        }

    return {
        "status": "update_available",
        "manual": manual,
        "automatic": automatic,
    }


def _github_unavailable_result(reason: str) -> BaseResult:
    """Friendly response when GitHub cannot be reached to check for updates."""
    releases_url = _releases_url()
    return BaseResult(
        result=[{
            "current_version": __version__,
            "latest_version": None,
            "update_available": None,
            "update_check_status": "unavailable",
            "reason": reason,
            "releases_url": releases_url,
            "platform": _platform_info(),
            "runtime": _detect_runtime(),
            "update_guidance": {
                "status": "unavailable",
                "manual": (
                    f"Update check could not reach GitHub. "
                    f"When you have access, open [{releases_url}]({releases_url}) "
                    f"and compare the latest release with your current version ({__version__})."
                ),
                "automatic": (
                    "Automatic update check is unavailable while GitHub cannot be reached. "
                    "Retry later or check releases from a network that can access GitHub."
                ),
            },
        }],
        warning=[
            "Could not reach GitHub to check for Perfecto MCP updates. "
            "This is common on restricted/corporate networks or when github.com is blocked."
        ],
        info=[
            f"You are running Perfecto MCP version {__version__}.",
            f"Check for newer releases manually at {releases_url} when GitHub is reachable.",
        ],
    )


def _github_access_failure_result(exc: Exception) -> BaseResult:
    if isinstance(exc, httpx.TimeoutException):
        return _github_unavailable_result(
            "Timed out while contacting GitHub. The network may be slow, filtered, or offline."
        )
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, httpx.ProxyError)):
        return _github_unavailable_result(
            "Could not connect to GitHub. The host may be offline, firewalled, or blocked from api.github.com."
        )
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            return _github_unavailable_result(
                f"GitHub refused the update check (HTTP {status}). "
                "Access may be blocked, require authentication, or be rate-limited."
            )
        if status == 404:
            return _github_unavailable_result(
                "GitHub release endpoint was not found (HTTP 404). "
                "The repository or releases URL may be unavailable from this network."
            )
        return _github_unavailable_result(
            f"GitHub returned an unexpected status while checking for updates (HTTP {status})."
        )
    if isinstance(exc, httpx.HTTPError):
        return _github_unavailable_result(
            "Could not complete the GitHub update check due to a network or HTTP error."
        )
    return _github_unavailable_result(
        "Could not complete the GitHub update check."
    )


class ToolsManager(Manager):
    def __init__(self, ctx: Context):
        super().__init__(ctx)

    async def version(self) -> BaseResult:
        platform_data = _platform_info()
        runtime = _detect_runtime()
        return BaseResult(
            result=[{
                "version": __version__,
                "user_agent": user_agent,
                "platform": platform_data,
                "runtime": runtime,
                "repository": GITHUB,
                "website": WEBSITE,
            }],
            info=[
                f"Perfecto MCP version {__version__}.",
                "Use action `check_updates` to compare against the latest GitHub release.",
            ],
        )

    async def check_updates(self) -> BaseResult:
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.get(GITHUB_API_LATEST_RELEASE, headers=headers)
                resp.raise_for_status()
                release = resp.json()
            except httpx.HTTPError as exc:
                return _github_access_failure_result(exc)
            except Exception as exc:
                return _github_access_failure_result(exc)

        tag_name = str(release.get("tag_name") or "")
        latest_version = tag_name.lstrip("vV") or str(release.get("name") or "")
        current = _parse_version(__version__)
        latest = _parse_version(latest_version)

        if current is None or latest is None:
            return BaseResult(
                error=(
                    f"Unable to compare versions. "
                    f"current={__version__!r}, latest={latest_version!r}."
                )
            )

        update_available = latest > current
        assets = [
            {
                "name": asset.get("name"),
                "browser_download_url": asset.get("browser_download_url"),
                "size": asset.get("size"),
                "content_type": asset.get("content_type"),
                "updated_at": asset.get("updated_at"),
            }
            for asset in (release.get("assets") or [])
        ]

        platform_data = _platform_info()
        runtime = _detect_runtime()
        recommended_asset = _match_recommended_asset(
            assets,
            platform_data["normalized_system"],
            platform_data["normalized_arch"],
        )
        guidance = _update_guidance(runtime, update_available, recommended_asset)

        info = []
        if update_available:
            info.append(
                f"Update available: current {__version__} -> latest {latest_version}."
            )
            info.append(
                "Share the release notes with the user and ask whether they want a manual "
                "update now or guidance for an automatic update path."
            )
            if recommended_asset:
                info.append(
                    f"Recommended download for this host: {recommended_asset.get('name')}."
                )
            else:
                info.append(
                    "No exact platform asset match was found; show the full assets list "
                    "so the user can pick the correct package."
                )
        else:
            info.append(f"Perfecto MCP is up to date (version {__version__}).")

        return BaseResult(
            result=[{
                "current_version": __version__,
                "latest_version": latest_version,
                "update_available": update_available,
                "release": {
                    "tag_name": tag_name,
                    "name": release.get("name"),
                    "html_url": release.get("html_url"),
                    "published_at": release.get("published_at"),
                    "body": release.get("body") or "",
                },
                "recommended_asset": recommended_asset,
                "assets": assets,
                "platform": platform_data,
                "runtime": runtime,
                "update_guidance": guidance,
            }],
            info=info,
        )


def register(mcp, runtime: AppRuntime):
    @mcp.tool(
        name=f"{TOOLS_PREFIX}_tools",
        description="""
Operations on Perfecto MCP tooling: version checks, session tasks, and session dataframes.
Actions:
- version: Return the current MCP version and runtime/platform information used by the
  user-agent and `--version` / console display.
- check_updates: Query the GitHub repository for the latest release, compare it with the
  current version, and return release notes plus download links when an update is available.
- tasks_get: Get task metadata by task ID and return task_result when terminal.
    args(dict): task_id (str, required); remove_on_terminal (bool, optional);
                wait_for_terminal_ms (int, optional); poll_interval_ms (int, optional)
- tasks_status: Lightweight task status by task ID (no task_result payload).
    args(dict): task_id (str, required); wait_for_terminal_ms (int, optional);
                poll_interval_ms (int, optional)
- tasks_list: List tasks for the current MCP session.
    args(dict): status (str, optional); status_list (list[str], optional)
- tasks_cancel: Cancel a running or queued task when this process owns it.
    args(dict): task_id (str, required)
- tasks_remove: Remove a task from the session registry.
    args(dict): task_id (str, required)
- dataframes_list: List dataframes and metadata for the current MCP session.
- dataframes_get: Get dataframe metadata and schema by dataframe ID.
    args(dict): dataframe_id (str, required)
- dataframes_schema_groups: Group dataframe schemas for multi-dataframe queries.
    args(dict): dataframe_id_list (list[str], optional)
- dataframes_query: Execute read-only SQL against session dataframe tables.
    args(dict): sql (str, required); output_format (matrix|columnar|records);
                result_format (auto|dataframe|raw, optional)
    requirement: ORDER BY + LIMIT + OFFSET are mandatory in every query.
- dataframes_remove: Remove one or more dataframes from the session store.
    args(dict): dataframe_id_list (list[str], required)
- dataframes_clear: Remove all dataframes for the current session.
- dataframes_sql_help: Describe supported SQL usage and blocked operations.
Hints:
- Prefer `version` first when the user asks what build they are running.
- Prefer `check_updates` when the user asks whether a newer MCP release exists.
- When an update is available, present release notes and ask before replacing the executable.
- If GitHub is unreachable (restricted network, firewall, timeout), explain that the update
  check is unavailable, still share the current version, and point to the releases page for a
  manual check — do not treat it as a hard failure.
- Render release and download URLs as markdown links.
- Before writing any dataframe SQL query, call `dataframes_sql_help`.
- ORDER BY + LIMIT + OFFSET are mandatory in every dataframe query.
- After a long-running tool returns a task snapshot, poll with tasks_status then tasks_get.
"""
    )
    async def tools(
            arguments: Dict[str, Any] = Field(description="Dictionary with arguments", default=None),
            ctx: Context = Field(description="Context object providing access to MCP capabilities")
    ) -> BaseResult:
        action, args = normalize_action_args(arguments)
        runtime.configure_context(ctx)
        tools_manager = ToolsManager(ctx)
        data_tools = DataTools(ctx, runtime.storage, runtime.scope_resolver)

        async def _dispatch():
            match action:
                case "version":
                    return await tools_manager.version()
                case "check_updates":
                    return await tools_manager.check_updates()
                case "tasks_get":
                    if validation_error := validate_required_args(action, args, ["task_id"]):
                        return validation_error
                    if err := validate_non_empty_str_arg(action, args, "task_id"):
                        return err
                    return await data_tools.tasks_get(
                        task_id=str(args.get("task_id", "")).strip(),
                        remove_on_terminal=bool(args.get("remove_on_terminal", True)),
                        wait_for_terminal_ms=int(args.get("wait_for_terminal_ms", 0) or 0),
                        poll_interval_ms=int(args.get("poll_interval_ms", 1000) or 1000),
                    )
                case "tasks_list":
                    return await data_tools.tasks_list(args.get("status"), args.get("status_list"))
                case "tasks_status":
                    if validation_error := validate_required_args(action, args, ["task_id"]):
                        return validation_error
                    if err := validate_non_empty_str_arg(action, args, "task_id"):
                        return err
                    return await data_tools.tasks_status(
                        task_id=str(args.get("task_id", "")).strip(),
                        wait_for_terminal_ms=int(args.get("wait_for_terminal_ms", 0) or 0),
                        poll_interval_ms=int(args.get("poll_interval_ms", 1000) or 1000),
                    )
                case "tasks_cancel":
                    if validation_error := validate_required_args(action, args, ["task_id"]):
                        return validation_error
                    if err := validate_non_empty_str_arg(action, args, "task_id"):
                        return err
                    return await data_tools.tasks_cancel(str(args.get("task_id", "")).strip())
                case "tasks_remove":
                    if validation_error := validate_required_args(action, args, ["task_id"]):
                        return validation_error
                    if err := validate_non_empty_str_arg(action, args, "task_id"):
                        return err
                    return await data_tools.tasks_remove(str(args.get("task_id", "")).strip())
                case "dataframes_list":
                    return await data_tools.dataframes_list()
                case "dataframes_get":
                    if validation_error := validate_required_args(action, args, ["dataframe_id"]):
                        return validation_error
                    if err := validate_non_empty_str_arg(action, args, "dataframe_id"):
                        return err
                    return await data_tools.dataframes_get(str(args.get("dataframe_id", "")).strip())
                case "dataframes_schema_groups":
                    return await data_tools.dataframes_schema_groups(args.get("dataframe_id_list"))
                case "dataframes_query":
                    if validation_error := validate_required_args(action, args, ["sql"]):
                        return validation_error
                    if err := validate_non_empty_str_arg(action, args, "sql"):
                        return err
                    return await data_tools.dataframes_query(
                        sql=str(args.get("sql", "")).strip(),
                        output_format=str(args.get("output_format", "matrix")),
                        result_format=str(args.get("result_format", "auto")),
                    )
                case "dataframes_remove":
                    if validation_error := validate_required_args(action, args, ["dataframe_id_list"]):
                        return validation_error
                    return await data_tools.dataframes_remove(args.get("dataframe_id_list"))
                case "dataframes_clear":
                    return await data_tools.dataframes_clear()
                case "dataframes_sql_help":
                    return await data_tools.dataframes_sql_help()
                case _:
                    return BaseResult(
                        error=f"Action {action} not found in tools manager tool"
                    )

        try:
            return await run_tool_with_runtime(
                runtime,
                f"{TOOLS_PREFIX}_tools",
                action,
                ctx,
                _dispatch,
                tool_args=args,
                dataframe_excluded_actions=set(TOOLS_ACTIONS_SKIP_AUTO_DATAFRAME),
            )
        except httpx.HTTPStatusError:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}"
            )
        except Exception:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}\n{SUPPORT_MESSAGE}"
            )
