"""
Copyright 2025 Perforce Software, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
import asyncio
import hashlib
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from update.install import copy_into_place_now, write_and_spawn_installer
from update.processes import (
    RunningProcess,
    find_other_instances,
    format_process_list,
    _matches_perfecto_mcp,
)
from update.release import (
    extract_update_payload,
    match_recommended_asset,
    verify_sha256,
)
from update.flow import describe_manual_update_instructions, run_interactive_update


def test_match_recommended_asset_prefers_zip():
    assets = [
        {"name": "perfecto-mcp-linux-amd64", "browser_download_url": "https://example.com/bin"},
        {"name": "perfecto-mcp-linux-amd64.zip", "browser_download_url": "https://example.com/zip"},
    ]
    matched = match_recommended_asset(assets, "linux", "amd64")
    assert matched["name"] == "perfecto-mcp-linux-amd64.zip"


def test_extract_update_payload_from_zip(tmp_path: Path):
    archive = tmp_path / "payload.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("perfecto-mcp-linux-amd64", b"binary-bytes")

    extracted = extract_update_payload(archive, tmp_path / "out")
    assert extracted.name == "perfecto-mcp-linux-amd64"
    assert extracted.read_bytes() == b"binary-bytes"


def test_extract_update_payload_prefers_app_bundle(tmp_path: Path):
    archive = tmp_path / "app.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("perfecto-mcp-arm64.app/Contents/MacOS/perfecto-mcp", b"app-bin")
        zf.writestr("perfecto-mcp-arm64.app/Contents/Info.plist", b"<plist/>")

    extracted = extract_update_payload(archive, tmp_path / "out")
    assert extracted.name.endswith(".app")
    assert (extracted / "Contents" / "MacOS" / "perfecto-mcp").read_bytes() == b"app-bin"


def test_extract_update_payload_ignores_macosx_appledouble(tmp_path: Path):
    archive = tmp_path / "app.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("perfecto-mcp-arm64.app/Contents/MacOS/perfecto-mcp", b"real-bin")
        zf.writestr("perfecto-mcp-arm64.app/Contents/Info.plist", b"<plist/>")
        zf.writestr("__MACOSX/perfecto-mcp-arm64.app/Contents/MacOS/._perfecto-mcp", b"junk")
        zf.writestr("__MACOSX/perfecto-mcp-arm64.app/Contents/._MacOS", b"junk")

    extracted = extract_update_payload(archive, tmp_path / "out")
    assert "__MACOSX" not in extracted.parts
    assert (extracted / "Contents" / "MacOS" / "perfecto-mcp").read_bytes() == b"real-bin"


def test_verify_sha256_accepts_matching_digest(tmp_path: Path):
    payload = tmp_path / "perfecto-mcp-linux-amd64"
    payload.write_bytes(b"abc")
    digest = hashlib.sha256(b"abc").hexdigest()
    verify_sha256(payload, f"{digest}  perfecto-mcp-linux-amd64\n")


def test_verify_sha256_rejects_mismatch(tmp_path: Path):
    payload = tmp_path / "bin"
    payload.write_bytes(b"abc")
    try:
        verify_sha256(payload, "0" * 64 + "  bin\n")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "mismatch" in str(exc).lower()


def test_format_process_list():
    text = format_process_list([
        RunningProcess(pid=11, name="perfecto-mcp", command="/tmp/perfecto-mcp --mcp"),
    ])
    assert "PID 11" in text
    assert "perfecto-mcp --mcp" in text


def test_find_other_instances_excludes_self():
    fake = [
        RunningProcess(pid=1, name="perfecto-mcp", command="perfecto-mcp --mcp"),
        RunningProcess(pid=2, name="perfecto-mcp", command="perfecto-mcp --update"),
    ]
    with patch("update.processes.list_perfecto_mcp_processes", return_value=fake), \
            patch("update.processes.os.getpid", return_value=1), \
            patch("update.processes.os.getppid", return_value=99):
        others = find_other_instances()
    assert [p.pid for p in others] == [2]


def test_matches_ignores_cursor_and_path_mentions():
    assert _matches_perfecto_mcp(
        "Cursor",
        "Cursor Helper (Plugin): extension-host (user) perfecto-mcp [1-35]",
    ) is False
    assert _matches_perfecto_mcp(
        "bash",
        "bash -c cd /Users/diego/Documents/perfecto-mcp && pytest",
    ) is False
    assert _matches_perfecto_mcp("perfecto-mcp", "perfecto-mcp --mcp") is True
    assert _matches_perfecto_mcp(
        "perfecto-mcp",
        "/Applications/perfecto-mcp-arm64.app/Contents/MacOS/perfecto-mcp --mcp",
    ) is True
    assert _matches_perfecto_mcp(
        "launcher.sh",
        "/Applications/perfecto-mcp-arm64.app/Contents/MacOS/launcher.sh",
    ) is True
    assert _matches_perfecto_mcp(
        "bash",
        "bash -lc '/opt/perfecto-mcp --mcp'",
    ) is True
    assert _matches_perfecto_mcp(
        "env",
        "env FOO=1 /usr/local/bin/perfecto-mcp --mcp",
    ) is True


def test_copy_into_place_replaces_file(tmp_path: Path):
    source = tmp_path / "new-bin"
    target = tmp_path / "old-bin"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    copy_into_place_now(source, target)
    assert target.read_bytes() == b"new"


def test_copy_into_place_replaces_app_inner_binary(tmp_path: Path):
    app = tmp_path / "perfecto-mcp-arm64.app"
    inner = app / "Contents" / "MacOS" / "perfecto-mcp"
    inner.parent.mkdir(parents=True)
    inner.write_bytes(b"old")
    source = tmp_path / "new-bin"
    source.write_bytes(b"new")
    copy_into_place_now(source, app)
    assert inner.read_bytes() == b"new"


def test_write_and_spawn_installer_unix(tmp_path: Path, monkeypatch):
    source = tmp_path / "src-bin"
    target = tmp_path / "dst-bin"
    source.write_bytes(b"x")
    target.write_bytes(b"y")
    spawned = {}

    def fake_mkstemp(prefix="tmp", suffix=""):
        import os
        path = tmp_path / f"{prefix}x{suffix}"
        fd = os.open(path, os.O_RDWR | os.O_CREAT)
        return fd, str(path)

    def fake_popen(cmd, **kwargs):
        spawned["cmd"] = cmd
        spawned["kwargs"] = kwargs
        return MagicMock()

    monkeypatch.setattr("update.install.tempfile.mkstemp", fake_mkstemp)
    monkeypatch.setattr("update.install.subprocess.Popen", fake_popen)
    monkeypatch.setattr("update.install.platform.system", lambda: "Linux")

    script = write_and_spawn_installer(source=source, target=target, wait_for_pid=12345)
    assert script.exists()
    content = script.read_text(encoding="utf-8")
    assert "12345" in content
    assert str(source.resolve()) in content
    assert str(target.resolve()) in content
    assert "restoring backup" in content.lower()
    assert spawned["cmd"][0] == "nohup"
    assert "/bin/bash" in spawned["cmd"]


def test_write_and_spawn_installer_darwin_opens_terminal(tmp_path: Path, monkeypatch):
    source = tmp_path / "src.app"
    (source / "Contents" / "MacOS").mkdir(parents=True)
    (source / "Contents" / "MacOS" / "perfecto-mcp").write_bytes(b"new")
    target = tmp_path / "dst.app"
    (target / "Contents" / "MacOS").mkdir(parents=True)
    (target / "Contents" / "MacOS" / "perfecto-mcp").write_bytes(b"old")
    spawned = {}

    def fake_mkstemp(prefix="tmp", suffix=""):
        import os
        path = tmp_path / f"{prefix}x{suffix}"
        fd = os.open(path, os.O_RDWR | os.O_CREAT)
        return fd, str(path)

    def fake_popen(cmd, **kwargs):
        spawned["cmd"] = cmd
        return MagicMock()

    monkeypatch.setattr("update.install.tempfile.mkstemp", fake_mkstemp)
    monkeypatch.setattr("update.install.subprocess.Popen", fake_popen)
    monkeypatch.setattr("update.install.platform.system", lambda: "Darwin")

    script = write_and_spawn_installer(source=source, target=target, wait_for_pid=99)
    content = script.read_text(encoding="utf-8")
    assert "open \"$DST\"" in content or 'open "$DST"' in content
    assert "failed to promote staged app" in content
    assert spawned["cmd"][:3] == ["open", "-a", "Terminal"]


def test_describe_manual_update_instructions_lists_steps():
    with patch("update.flow.find_other_instances", return_value=[]), \
            patch(
                "update.flow._runtime_supports_inplace_update",
                return_value=(True, ""),
            ), \
            patch("update.flow.sys.platform", "linux"), \
            patch("update.flow.__bundle__", "/tmp/perfecto-mcp"), \
            patch("update.flow.__executable__", "/tmp/perfecto-mcp"):
        guidance = describe_manual_update_instructions()
    assert guidance["supported"] is True
    assert guidance["other_instances_running"] == []
    assert any("quit" in step.lower() for step in guidance["steps"])


def test_run_interactive_update_blocks_when_not_frozen():
    with patch("update.flow.__uvx__", False), \
            patch(
                "update.flow._runtime_supports_inplace_update",
                return_value=(False, "not frozen"),
            ):
        code = run_interactive_update(auto_confirm=True)
    assert code == 1


def test_run_interactive_update_spawns_and_returns_without_sys_exit():
    release = MagicMock()
    release.update_available = True
    release.current_version = "1.0.0"
    release.latest_version = "1.1.1"
    release.html_url = "https://example.com"
    release.body = ""
    release.recommended_asset = {
        "name": "perfecto-mcp-macos-arm64.zip",
        "browser_download_url": "https://example.com/a.zip",
    }
    release.assets = [release.recommended_asset]

    with patch("update.flow.__uvx__", False), \
            patch("update.flow._runtime_supports_inplace_update", return_value=(True, "")), \
            patch("update.flow.fetch_latest_release", return_value=release), \
            patch("update.flow.find_other_instances", return_value=[]), \
            patch("update.flow.stage_update_from_asset", return_value=Path("/tmp/staged")), \
            patch("update.flow.write_and_spawn_installer", return_value=Path("/tmp/install.sh")) as spawn, \
            patch("update.flow.install_target_path", return_value=Path("/tmp/app.app")):
        code = run_interactive_update(auto_confirm=True)

    assert code == 0
    spawn.assert_called_once()


def test_update_status_tool(perfecto_token):
    from tools.tools_manager import ToolsManager

    manager = ToolsManager(perfecto_token, MagicMock())
    with patch("tools.tools_manager.find_other_instances", return_value=[]), \
            patch("tools.tools_manager.describe_manual_update_instructions", return_value={
                "supported": True,
                "steps": ["step"],
                "other_instances_running": [],
            }):
        result = asyncio.run(manager.update_status())

    assert result.error is None
    assert result.result[0]["manual_update"]["supported"] is True
    assert any("quit" in message.lower() for message in result.info)
