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
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from tests.conftest import make_ctx
from tools.tools_manager import (
    ToolsManager,
    _match_recommended_asset,
    _normalize_arch,
    _normalize_system,
)


def test_version_returns_current_build_metadata(perfecto_token):
    manager = ToolsManager(make_ctx(perfecto_token))
    result = asyncio.run(manager.version())

    assert result.error is None
    assert len(result.result) == 1
    payload = result.result[0]
    assert payload["version"]
    assert payload["user_agent"].startswith(f"perfecto-mcp/{payload['version']}")
    assert "platform" in payload
    assert "runtime" in payload
    assert result.info
    assert any("check_updates" in message for message in result.info)


def test_normalize_platform_helpers():
    assert _normalize_system("Darwin") == "macos"
    assert _normalize_system("Windows") == "windows"
    assert _normalize_system("Linux") == "linux"
    assert _normalize_arch("x86_64") == "amd64"
    assert _normalize_arch("amd64") == "amd64"
    assert _normalize_arch("arm64") == "arm64"
    assert _normalize_arch("aarch64") == "arm64"


def test_match_recommended_asset_prefers_zip():
    assets = [
        {
            "name": "perfecto-mcp-macos-arm64",
            "browser_download_url": "https://example.com/bin",
        },
        {
            "name": "perfecto-mcp-macos-arm64.zip",
            "browser_download_url": "https://example.com/zip",
        },
    ]
    matched = _match_recommended_asset(assets, "macos", "arm64")
    assert matched["name"] == "perfecto-mcp-macos-arm64.zip"


def test_check_updates_when_latest_is_newer(perfecto_token):
    release = {
        "tag_name": "v9.9.9",
        "name": "v9.9.9",
        "html_url": "https://github.com/PerfectoCode/perfecto-mcp/releases/tag/v9.9.9",
        "published_at": "2026-07-14T00:00:00Z",
        "body": "Release notes for 9.9.9",
        "assets": [
            {
                "name": "perfecto-mcp-macos-arm64.zip",
                "browser_download_url": "https://example.com/perfecto-mcp-macos-arm64.zip",
                "size": 123,
                "content_type": "application/zip",
                "updated_at": "2026-07-14T00:00:00Z",
            }
        ],
    }

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=release)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("tools.tools_manager.httpx.AsyncClient", return_value=mock_client), \
            patch("tools.tools_manager.__version__", "1.0.0"), \
            patch("tools.tools_manager.platform.system", return_value="Darwin"), \
            patch("tools.tools_manager.platform.machine", return_value="arm64"):
        manager = ToolsManager(make_ctx(perfecto_token))
        result = asyncio.run(manager.check_updates())

    assert result.error is None
    payload = result.result[0]
    assert payload["update_available"] is True
    assert payload["current_version"] == "1.0.0"
    assert payload["latest_version"] == "9.9.9"
    assert payload["release"]["body"] == "Release notes for 9.9.9"
    assert payload["recommended_asset"]["name"] == "perfecto-mcp-macos-arm64.zip"
    assert payload["update_guidance"]["status"] == "update_available"


def test_check_updates_when_up_to_date(perfecto_token):
    release = {
        "tag_name": "v1.1.1",
        "name": "v1.1.1",
        "html_url": "https://github.com/PerfectoCode/perfecto-mcp/releases/tag/v1.1.1",
        "published_at": "2026-07-09T00:00:00Z",
        "body": "Up to date notes",
        "assets": [],
    }

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=release)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("tools.tools_manager.httpx.AsyncClient", return_value=mock_client), \
            patch("tools.tools_manager.__version__", "1.1.1"):
        manager = ToolsManager(make_ctx(perfecto_token))
        result = asyncio.run(manager.check_updates())

    assert result.error is None
    payload = result.result[0]
    assert payload["update_available"] is False
    assert payload["update_guidance"]["status"] == "up_to_date"


def test_check_updates_http_error(perfecto_token):
    mock_response = MagicMock()
    mock_response.status_code = 500
    request = httpx.Request("GET", "https://api.github.com")
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("boom", request=request, response=mock_response)
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("tools.tools_manager.httpx.AsyncClient", return_value=mock_client):
        manager = ToolsManager(make_ctx(perfecto_token))
        result = asyncio.run(manager.check_updates())

    assert result.error is None
    payload = result.result[0]
    assert payload["update_check_status"] == "unavailable"
    assert payload["update_available"] is None
    assert payload["latest_version"] is None
    assert "releases" in payload["releases_url"]
    assert result.warning
    assert any("Could not reach GitHub" in message for message in result.warning)
    assert result.info
    assert any("running Perfecto MCP version" in message for message in result.info)


def test_check_updates_connect_error(perfecto_token):
    request = httpx.Request("GET", "https://api.github.com")
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("dns failed", request=request))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("tools.tools_manager.httpx.AsyncClient", return_value=mock_client), \
            patch("tools.tools_manager.__version__", "1.1.1"):
        manager = ToolsManager(make_ctx(perfecto_token))
        result = asyncio.run(manager.check_updates())

    assert result.error is None
    payload = result.result[0]
    assert payload["update_check_status"] == "unavailable"
    assert payload["current_version"] == "1.1.1"
    assert "connect" in payload["reason"].lower() or "blocked" in payload["reason"].lower()
    assert payload["update_guidance"]["status"] == "unavailable"


def test_check_updates_timeout(perfecto_token):
    request = httpx.Request("GET", "https://api.github.com")
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ReadTimeout("timed out", request=request))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("tools.tools_manager.httpx.AsyncClient", return_value=mock_client):
        manager = ToolsManager(make_ctx(perfecto_token))
        result = asyncio.run(manager.check_updates())

    assert result.error is None
    payload = result.result[0]
    assert payload["update_check_status"] == "unavailable"
    assert "Timed out" in payload["reason"]
    assert any("corporate" in message for message in (result.warning or []))
