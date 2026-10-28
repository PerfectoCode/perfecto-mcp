"""Interactive (double-click / --update) manual update flow."""

from __future__ import annotations

import platform
import sys
from typing import Callable, List, Optional

import httpx

from config.perfecto import GITHUB
from config.version import __bundle__, __executable__, __uvx__, __version__
from update.install import install_target_path, update_log_path, write_and_spawn_installer
from update.processes import RunningProcess, find_other_instances, format_process_list
from update.release import fetch_latest_release, stage_update_from_asset


PromptFn = Callable[[str], str]


def _default_prompt(message: str) -> str:
    return input(message)


def _runtime_supports_inplace_update() -> tuple[bool, str]:
    if __uvx__:
        return False, (
            "This process was started via uvx. Update by changing the git ref in your "
            f"MCP client config (see {GITHUB}/releases), then restart the client."
        )
    if not getattr(sys, "frozen", False):
        return False, (
            "In-place binary update only applies to frozen PyInstaller builds. "
            f"For source/dev installs, pull the latest tag from {GITHUB}."
        )
    return True, ""


def _wait_until_no_other_instances(prompt: PromptFn) -> bool:
    while True:
        others = find_other_instances()
        if not others:
            print(" No other Perfecto MCP processes are running. Continuing.")
            return True

        print(" Perfecto MCP is still running elsewhere. Close it before updating:\n")
        print(format_process_list(others))
        print()
        print(" Typical causes:")
        print("  - An MCP client (Cursor, VS Code, Claude Desktop, …) still has the server attached")
        print("  - Another Terminal window running perfecto-mcp")
        print()
        print(" Close those sessions, then press Enter to re-check (or type 'q' to cancel).")
        answer = prompt("> ").strip().lower()
        if answer in {"q", "quit", "exit", "n", "no"}:
            return False


def run_interactive_update(*, prompt: Optional[PromptFn] = None, auto_confirm: bool = False) -> int:
    """
    Run the manual update wizard.

    Returns a process exit code. On success after spawning the installer, returns 0;
    the caller must exit the process so files can be replaced.
    """
    prompt = prompt or _default_prompt

    print(f" Perfecto MCP updater (current version {__version__})")
    print(f" Install target: {install_target_path()}")
    print()

    supported, reason = _runtime_supports_inplace_update()
    if not supported:
        print(f" {reason}")
        return 1

    try:
        release = fetch_latest_release()
    except httpx.HTTPError as exc:
        print(f" Could not reach GitHub to check for updates: {exc}")
        print(f" Open {GITHUB}/releases when you have network access.")
        return 1
    except ValueError as exc:
        print(f" {exc}")
        return 1

    if not release.update_available:
        print(f" Already up to date (latest is {release.latest_version}).")
        return 0

    print(f" Update available: {release.current_version} -> {release.latest_version}")
    print(f" Release: {release.html_url}")
    if release.body.strip():
        print()
        print(" Release notes (truncated):")
        for line in release.body.strip().splitlines()[:12]:
            print(f"  {line}")
        print()

    asset = release.recommended_asset
    if not asset:
        print(" No download asset matched this platform. Open the releases page and install manually:")
        print(f"  {release.html_url}")
        return 1

    print(f" Recommended package: {asset.get('name')}")
    print()
    print(" Before updating:")
    print("  1. Quit / disable Perfecto MCP in every MCP client so no server process remains.")
    print("  2. Keep this window open and follow the prompts.")
    print("  3. After install, the app relaunches; reopen the MCP client if needed.")
    print()

    if not auto_confirm:
        answer = prompt(" Download and install this update now? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            print(" Update cancelled.")
            return 0

    if not _wait_until_no_other_instances(prompt):
        print(" Update cancelled while Perfecto MCP was still running.")
        return 1

    print(" Downloading update…")
    try:
        staged = stage_update_from_asset(asset, all_assets=release.assets)
    except (httpx.HTTPError, OSError, ValueError, FileNotFoundError) as exc:
        print(f" Download/extract failed: {exc}")
        return 1

    # Re-check immediately before spawn — a client may have reconnected during download.
    if find_other_instances():
        print(" Perfecto MCP started again during download. Close it, then re-run the updater.")
        return 1

    print(f" Staged payload: {staged}")
    if platform.system() == "Darwin":
        print(" Launching install helper in a new Terminal window.")
    else:
        print(" Launching background install helper (progress is written to the log file).")
    print(" It waits for this process (and any other Perfecto MCP processes) to exit,")
    print(" then replaces the app and relaunches it.")
    script = write_and_spawn_installer(source=staged)
    print(f" Install script: {script}")
    print(f" Install log: {update_log_path()}")
    print(" Exiting so the install helper can replace files…")
    return 0


def describe_manual_update_instructions(
    *,
    others: Optional[List[RunningProcess]] = None,
) -> dict:
    """Structured guidance for MCP tools / agents."""
    supported, reason = _runtime_supports_inplace_update()
    if others is None:
        others = find_other_instances()
    target = str(install_target_path())
    if sys.platform == "darwin" and str(__bundle__).endswith(".app"):
        launch_hint = (
            f"Double-click `{__bundle__}` (or run it from Finder). "
            "A Terminal window opens with on-screen update instructions."
        )
    else:
        launch_hint = (
            f"Quit the MCP client session, then run `{__executable__}` without `--mcp` "
            "(or with `--update`) and follow the on-screen instructions."
        )

    return {
        "supported": supported,
        "unsupported_reason": reason or None,
        "install_target": target,
        "this_session_must_quit": True,
        "this_session_note": (
            "This MCP tool call is running inside a live Perfecto MCP process. "
            "That process (and any MCP client attached to it) must be stopped before "
            "files can be replaced. Reconnection after quit is expected and normal."
        ),
        "other_instances_running": [
            {"pid": p.pid, "name": p.name, "command": p.command} for p in others
        ],
        "steps": [
            "Tell the user an update requires quitting Perfecto MCP in every MCP client first "
            "(this live session cannot overwrite its own executable).",
            "Call out any other Perfecto MCP processes from other_instances_running and ask the user to close them.",
            launch_hint,
            "In the updater window, confirm no processes remain, download, and wait until install succeeds.",
            "Re-enable / reopen the MCP client so it reconnects to the new binary.",
        ],
    }
