"""
Platform install helpers inspired by tufup.

Frozen executables cannot safely overwrite themselves while running. The pattern is:
1. Stage the new files somewhere else.
2. Spawn a short-lived script/process that waits for this PID to exit.
3. Replace the install target, then relaunch (MCP clients typically reconnect afterward).
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Optional, Union

from config.version import __bundle__, __executable__
from update.release import BINARY_NAME

PathLike = Union[str, Path]
UPDATE_LOG_NAME = f"{BINARY_NAME}-update.log"


def install_target_path() -> Path:
    """Directory or file that should be replaced for this runtime."""
    if sys.platform == "darwin" and str(__bundle__).endswith(".app"):
        return Path(__bundle__).resolve()
    return Path(__executable__).resolve()


def update_log_path(target: Optional[Path] = None) -> Path:
    path = target if target is not None else install_target_path()
    return path.parent / UPDATE_LOG_NAME


def _is_app_bundle(path: Path) -> bool:
    return path.suffix == ".app" or str(path).endswith(".app")


def _unix_wait_and_log_header(*, pid: int, log_file: Path) -> str:
    log_q = str(log_file)
    return textwrap.dedent(
        f"""\
        #!/bin/bash
        set -euo pipefail
        LOG_FILE="{log_q}"
        mkdir -p "$(dirname "$LOG_FILE")"
        exec > >(tee -a "$LOG_FILE") 2>&1
        echo "Waiting for Perfecto MCP (PID {pid}) to exit..."
        while kill -0 {pid} 2>/dev/null; do
          sleep 1
        done
        echo "Ensuring no other Perfecto MCP processes remain..."
        SELF_PID=$$
        while true; do
          FOUND=0
          while read -r OPID OCMD; do
            [ -z "${{OPID:-}}" ] && continue
            [ "$OPID" = "$SELF_PID" ] && continue
            case "$OCMD" in
              *{BINARY_NAME}-install-*) continue ;;
              *tee\\ -a*\"$LOG_FILE\"*|*"$LOG_FILE"*) continue ;;
            esac
            case "$OCMD" in
              */Contents/MacOS/{BINARY_NAME}*|*/{BINARY_NAME}\\ --*|*/{BINARY_NAME}|*/{BINARY_NAME}.exe*)
                FOUND=1
                break
                ;;
            esac
          done < <(ps -ax -o pid=,command= 2>/dev/null || true)
          [ "$FOUND" -eq 0 ] && break
          echo "Waiting for remaining Perfecto MCP processes to exit..."
          sleep 1
        done
        """
    )


def _unix_script_footer() -> str:
    return textwrap.dedent(
        """\
        echo "Done. You can close this window."
        rm -f -- "$0"
        """
    )


def _macos_app_bundle_script(*, pid: int, source: Path, target: Path, log_file: Path) -> str:
    source_q = str(source)
    target_q = str(target)
    header = _unix_wait_and_log_header(pid=pid, log_file=log_file)
    body = textwrap.dedent(
        f"""\
        SRC="{source_q}"
        DST="{target_q}"
        BACKUP="${{DST}}.bak.$$"
        STAGE="${{DST}}.new.$$"
        echo "Installing update into $DST ..."
        if [ ! -d "$SRC" ] || [ ! -f "$SRC/Contents/MacOS/{BINARY_NAME}" ]; then
          echo "ERROR: staged update is not a usable .app (missing Contents/MacOS/{BINARY_NAME})."
          echo "SRC=$SRC"
          exit 1
        fi
        rm -rf "$STAGE" "$BACKUP"
        if command -v ditto >/dev/null 2>&1; then
          ditto "$SRC" "$STAGE"
        else
          cp -R "$SRC" "$STAGE"
        fi
        chmod 755 "$STAGE/Contents/MacOS/{BINARY_NAME}" 2>/dev/null || true
        chmod 755 "$STAGE/Contents/MacOS/launcher.sh" 2>/dev/null || true
        mv "$DST" "$BACKUP"
        if ! mv "$STAGE" "$DST"; then
          echo "ERROR: failed to promote staged app; restoring backup."
          mv "$BACKUP" "$DST" || true
          rm -rf "$STAGE" || true
          exit 1
        fi
        rm -rf "$BACKUP"
        echo "Update installed successfully."
        echo "Relaunching Perfecto MCP..."
        open "$DST" || true
        """
    )
    return header + body + _unix_script_footer()


def _macos_inner_binary_script(
    *, pid: int, source: Path, target: Path, log_file: Path
) -> str:
    source_q = str(source)
    target_q = str(target)
    header = _unix_wait_and_log_header(pid=pid, log_file=log_file)
    body = textwrap.dedent(
        f"""\
        SRC="{source_q}"
        DST="{target_q}"
        INNER="$DST/Contents/MacOS/{BINARY_NAME}"
        BACKUP="${{INNER}}.bak.$$"
        echo "Installing binary update into $INNER ..."
        if [ ! -f "$SRC" ]; then
          echo "ERROR: staged binary not found: $SRC"
          exit 1
        fi
        if [ ! -d "$DST/Contents/MacOS" ]; then
          echo "ERROR: install target is not a usable .app: $DST"
          exit 1
        fi
        cp "$INNER" "$BACKUP"
        if ! cp "$SRC" "$INNER"; then
          echo "ERROR: failed to replace inner binary; restoring backup."
          cp "$BACKUP" "$INNER" || true
          exit 1
        fi
        chmod 755 "$INNER"
        rm -f "$BACKUP"
        echo "Update installed successfully."
        echo "Relaunching Perfecto MCP..."
        open "$DST" || true
        """
    )
    return header + body + _unix_script_footer()


def _linux_or_macos_file_script(
    *, pid: int, source: Path, target: Path, log_file: Path
) -> str:
    source_q = str(source)
    target_q = str(target)
    header = _unix_wait_and_log_header(pid=pid, log_file=log_file)
    body = textwrap.dedent(
        f"""\
        SRC="{source_q}"
        DST="{target_q}"
        BACKUP="${{DST}}.bak.$$"
        echo "Installing update to $DST ..."
        if [ ! -f "$SRC" ]; then
          echo "ERROR: staged update binary not found: $SRC"
          exit 1
        fi
        cp "$DST" "$BACKUP"
        if ! cp "$SRC" "$DST"; then
          echo "ERROR: failed to replace binary; restoring backup."
          cp "$BACKUP" "$DST" || true
          exit 1
        fi
        chmod 755 "$DST"
        rm -f "$BACKUP"
        echo "Update installed successfully."
        if [ "$(uname -s)" = "Darwin" ]; then
          open "$DST" || true
        else
          nohup "$DST" >/dev/null 2>&1 &
        fi
        """
    )
    return header + body + _unix_script_footer()


def _windows_script(*, pid: int, source: Path, target: Path, log_file: Path) -> str:
    source_q = str(source)
    target_q = str(target)
    log_q = str(log_file)
    return textwrap.dedent(
        f"""\
        @echo off
        setlocal
        set "LOG_FILE={log_q}"
        echo Waiting for Perfecto MCP (PID {pid}) to exit...>>"%LOG_FILE%"
        :waitloop
        tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL
        if not errorlevel 1 (
          timeout /t 1 /nobreak >NUL
          goto waitloop
        )
        echo Ensuring no other Perfecto MCP processes remain...>>"%LOG_FILE%"
        :waitothers
        tasklist /FI "IMAGENAME eq {BINARY_NAME}*" 2>NUL | find /I "{BINARY_NAME}" >NUL
        if not errorlevel 1 (
          timeout /t 1 /nobreak >NUL
          goto waitothers
        )
        set "SRC={source_q}"
        set "DST={target_q}"
        set "BACKUP=%DST%.bak.%RANDOM%"
        echo Installing update to %DST% ...>>"%LOG_FILE%"
        copy /Y "%DST%" "%BACKUP%" >NUL
        copy /Y "%SRC%" "%DST%" >NUL
        if errorlevel 1 (
          echo Update failed. Restoring backup...>>"%LOG_FILE%"
          copy /Y "%BACKUP%" "%DST%" >NUL
          exit /b 1
        )
        del /F /Q "%BACKUP%" >NUL 2>&1
        echo Update installed successfully.>>"%LOG_FILE%"
        start "" "%DST%"
        echo Done.>>"%LOG_FILE%"
        (goto) 2>nul & del "%~f0"
        """
    )


def write_and_spawn_installer(
    *,
    source: PathLike,
    target: Optional[PathLike] = None,
    wait_for_pid: Optional[int] = None,
) -> Path:
    """
    Write a platform-specific install script and start it in a detached process.

    Does not exit the current process; caller should exit after spawning.
    """
    source_path = Path(source).resolve()
    target_path = Path(target).resolve() if target is not None else install_target_path()
    pid = wait_for_pid if wait_for_pid is not None else os.getpid()
    system = platform.system()
    log_file = update_log_path(target_path)

    if system == "Windows":
        content = _windows_script(
            pid=pid, source=source_path, target=target_path, log_file=log_file
        )
        suffix = ".bat"
    else:
        is_app = _is_app_bundle(target_path)
        if is_app and system == "Darwin" and source_path.is_file():
            content = _macos_inner_binary_script(
                pid=pid, source=source_path, target=target_path, log_file=log_file
            )
        elif is_app and system == "Darwin":
            content = _macos_app_bundle_script(
                pid=pid, source=source_path, target=target_path, log_file=log_file
            )
        else:
            content = _linux_or_macos_file_script(
                pid=pid, source=source_path, target=target_path, log_file=log_file
            )
        suffix = ".sh"

    fd, script_name = tempfile.mkstemp(prefix=f"{BINARY_NAME}-install-", suffix=suffix)
    os.close(fd)
    script_path = Path(script_name)
    script_path.write_text(content, encoding="utf-8")

    if system == "Windows":
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(["cmd.exe", "/c", str(script_path)], creationflags=creationflags)
    else:
        script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if system == "Darwin":
            subprocess.Popen(["open", "-a", "Terminal", str(script_path)])
        else:
            subprocess.Popen(
                ["nohup", "/bin/bash", str(script_path)],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    return script_path


def copy_into_place_now(source: PathLike, target: Optional[PathLike] = None) -> Path:
    """Synchronous replace used by tests / when the target is not locked."""
    source_path = Path(source).resolve()
    target_path = Path(target).resolve() if target is not None else install_target_path()
    if _is_app_bundle(target_path):
        if source_path.is_dir() and source_path.name.endswith(".app"):
            if target_path.exists():
                shutil.rmtree(target_path)
            shutil.copytree(source_path, target_path)
        else:
            inner = target_path / "Contents" / "MacOS" / BINARY_NAME
            inner.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, inner)
            os.chmod(inner, 0o755)
    else:
        shutil.copy2(source_path, target_path)
        if platform.system() != "Windows":
            os.chmod(target_path, 0o755)
    return target_path
