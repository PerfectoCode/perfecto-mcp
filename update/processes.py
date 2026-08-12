"""Detect other running Perfecto MCP instances before applying an update."""

from __future__ import annotations

import os
import platform
import re
import subprocess
from dataclasses import dataclass
from typing import List, Optional

from update.release import BINARY_NAME


@dataclass(frozen=True)
class RunningProcess:
    pid: int
    name: str
    command: str


_APP_LAUNCHER_RE = re.compile(
    rf"{re.escape(BINARY_NAME)}[^/\s]*\.app/Contents/MacOS/",
    re.IGNORECASE,
)
# Absolute/relative path to the binary (not a bare workspace-name token).
_BINARY_PATH_RE = re.compile(
    rf"(?:^|[\s\"'=])((?:[A-Za-z]:)?(?:[/\\][^\s\"']*)?[/\\]{re.escape(BINARY_NAME)}"
    rf"(?:-[A-Za-z0-9._]+)?(?:\.exe)?)(?=[\s\"']|$)",
    re.IGNORECASE,
)


def _executable_basename(token: str) -> str:
    token = token.strip().strip('"').strip("'")
    return os.path.basename(token).lower()


def _matches_perfecto_mcp(name: str, command: str) -> bool:
    """
    Match real Perfecto MCP server processes only.

    Avoid false positives from IDE helpers, shells, or paths that merely mention
    the repository name (e.g. Cursor extension-host titles containing 'perfecto-mcp').
    """
    name_base = _executable_basename(name.split()[0] if name else "")
    if name_base.startswith(BINARY_NAME):
        return True

    command = command.strip()
    if not command:
        return False

    first = _executable_basename(command.split()[0])
    if first.startswith(BINARY_NAME):
        return True

    normalized = command.replace("\\", "/")
    if _APP_LAUNCHER_RE.search(normalized):
        return True

    if _BINARY_PATH_RE.search(normalized):
        # `cd /.../perfecto-mcp && pytest` mentions the repo dir, not the binary.
        if re.search(r"\bcd\s+", command) and "--mcp" not in command and "--update" not in command:
            return False
        return True

    return False


def _parse_ps_line(line: str) -> Optional[RunningProcess]:
    line = line.strip()
    if not line:
        return None
    parts = line.split(None, 1)
    if len(parts) < 2 or not parts[0].isdigit():
        return None
    pid = int(parts[0])
    command = parts[1]
    name = _executable_basename(command.split()[0]) if command else ""
    if not _matches_perfecto_mcp(name, command):
        return None
    return RunningProcess(pid=pid, name=name, command=command)


def _list_unix_processes() -> List[RunningProcess]:
    try:
        completed = subprocess.run(
            ["ps", "-ax", "-o", "pid=,command="],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []

    found: List[RunningProcess] = []
    for line in completed.stdout.splitlines():
        proc = _parse_ps_line(line)
        if proc is not None:
            found.append(proc)
    return found


def _list_windows_processes() -> List[RunningProcess]:
    try:
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []

    found: List[RunningProcess] = []
    for line in completed.stdout.splitlines():
        fields = _split_csv_fields(line)
        if len(fields) < 2:
            continue
        name = fields[0]
        pid_text = fields[1]
        if not pid_text.isdigit():
            continue
        if not _matches_perfecto_mcp(name, name):
            continue
        found.append(RunningProcess(pid=int(pid_text), name=name, command=name))
    return found


def _split_csv_fields(line: str) -> List[str]:
    return re.findall(r'"([^"]*)"', line)


def list_perfecto_mcp_processes() -> List[RunningProcess]:
    if platform.system() == "Windows":
        return _list_windows_processes()
    return _list_unix_processes()


def find_other_instances(exclude_pid: Optional[int] = None) -> List[RunningProcess]:
    """Return Perfecto MCP processes other than this one (and its direct parent)."""
    if exclude_pid is None:
        exclude_pid = os.getpid()
    parent_pid = os.getppid()
    excluded = {exclude_pid, parent_pid}
    return [proc for proc in list_perfecto_mcp_processes() if proc.pid not in excluded]


def format_process_list(processes: List[RunningProcess]) -> str:
    if not processes:
        return "(none)"
    return "\n".join(f"  PID {proc.pid}: {proc.command}" for proc in processes)
