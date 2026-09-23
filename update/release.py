"""GitHub release lookup and asset download for the manual updater."""

from __future__ import annotations

import hashlib
import platform
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from packaging.version import InvalidVersion, Version

from config.http import timeout, user_agent
from config.perfecto import GITHUB, GITHUB_API_LATEST_RELEASE
from config.platform_names import normalize_arch, normalize_system
from config.version import __version__

BINARY_NAME = "perfecto-mcp"
APPLEDOUBLE_DIR = "__MACOSX"


def parse_version(value: str) -> Optional[Version]:
    try:
        return Version(str(value).lstrip("vV"))
    except InvalidVersion:
        return None


def match_recommended_asset(
    assets: List[Dict[str, Any]], system: str, arch: str
) -> Optional[Dict[str, Any]]:
    prefix = f"{BINARY_NAME}-{system}-{arch}"
    exact = [
        asset for asset in assets
        if str(asset.get("name", "")).startswith(prefix)
        and not str(asset.get("name", "")).endswith(".sha256")
    ]
    if not exact:
        return None
    zip_assets = [asset for asset in exact if str(asset.get("name", "")).endswith(".zip")]
    if zip_assets:
        return zip_assets[0]
    app_assets = [asset for asset in exact if ".app" in str(asset.get("name", "")).lower()]
    if app_assets:
        return app_assets[0]
    return exact[0]


def find_checksum_asset(
    assets: List[Dict[str, Any]], asset: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    name = str(asset.get("name") or "")
    if not name:
        return None
    wanted = {f"{name}.sha256", name.replace(".zip", "") + ".sha256"}
    for candidate in assets:
        candidate_name = str(candidate.get("name") or "")
        if candidate_name in wanted or candidate_name == f"{name}.sha256":
            return candidate
    return None


@dataclass
class LatestRelease:
    tag_name: str
    latest_version: str
    html_url: str
    body: str
    assets: List[Dict[str, Any]]
    recommended_asset: Optional[Dict[str, Any]]
    update_available: bool
    current_version: str


def fetch_latest_release(client: Optional[httpx.Client] = None) -> LatestRelease:
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=timeout)

    try:
        resp = client.get(GITHUB_API_LATEST_RELEASE, headers=headers)
        resp.raise_for_status()
        release = resp.json()
    finally:
        if owns_client:
            client.close()

    return latest_release_from_payload(release, current_version=__version__)


def latest_release_from_payload(
    release: Dict[str, Any], *, current_version: str
) -> LatestRelease:
    tag_name = str(release.get("tag_name") or "")
    latest_version = tag_name.lstrip("vV") or str(release.get("name") or "")
    current = parse_version(current_version)
    latest = parse_version(latest_version)
    if current is None or latest is None:
        raise ValueError(
            f"Unable to compare versions. current={current_version!r}, latest={latest_version!r}."
        )

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
    recommended = match_recommended_asset(
        assets,
        normalize_system(platform.system()),
        normalize_arch(platform.machine()),
    )
    return LatestRelease(
        tag_name=tag_name,
        latest_version=latest_version,
        html_url=str(release.get("html_url") or f"{GITHUB}/releases"),
        body=str(release.get("body") or ""),
        assets=assets,
        recommended_asset=recommended,
        update_available=latest > current,
        current_version=current_version,
    )


def download_asset(asset: Dict[str, Any], dest_dir: Path) -> Path:
    url = asset.get("browser_download_url")
    name = str(asset.get("name") or "download.bin")
    if not url:
        raise ValueError("Recommended release asset has no download URL.")

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / name
    headers = {"User-Agent": user_agent, "Accept": "application/octet-stream"}

    with httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0), follow_redirects=True) as client:
        with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as out:
                for chunk in resp.iter_bytes():
                    out.write(chunk)
    return dest_path


def verify_sha256(file_path: Path, checksum_text: str) -> None:
    """Raise ValueError if file contents do not match a sha256sum-style checksum file."""
    expected = None
    for line in checksum_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Fa-f0-9]{64})(?:\s+\*?(\S+))?$", line)
        if match:
            expected = match.group(1).lower()
            break
    if expected is None:
        raise ValueError("Checksum file did not contain a usable SHA-256 digest.")

    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise ValueError(
            f"SHA-256 mismatch for {file_path.name}: expected {expected}, got {actual}."
        )


def extract_update_payload(archive_or_file: Path, extract_dir: Path) -> Path:
    """
    Return the path to install: either an extracted .app, extracted binary, or the file itself.
    """
    extract_dir.mkdir(parents=True, exist_ok=True)

    if archive_or_file.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive_or_file, "r") as zf:
            zf.extractall(extract_dir)
        return _select_extracted_payload(extract_dir)

    return archive_or_file


def _is_appledouble_junk(path: Path) -> bool:
    return APPLEDOUBLE_DIR in path.parts or path.name.startswith("._")


def _is_usable_app_bundle(path: Path) -> bool:
    if not path.is_dir() or not path.name.endswith(".app") or _is_appledouble_junk(path):
        return False
    binary = path / "Contents" / "MacOS" / BINARY_NAME
    return binary.is_file() and binary.stat().st_size > 0


def _select_extracted_payload(extract_dir: Path) -> Path:
    apps = [
        path for path in extract_dir.rglob("*.app")
        if _is_usable_app_bundle(path)
    ]
    if apps:
        apps.sort(key=lambda p: (len(p.parts), str(p)))
        return apps[0]

    candidates = [
        path for path in extract_dir.rglob("*")
        if path.is_file()
        and not _is_appledouble_junk(path)
        and BINARY_NAME in path.name.lower()
        and not path.name.endswith(".sha256")
        and not path.name.startswith("._")
    ]
    if not candidates:
        raise FileNotFoundError(
            "Zip archive did not contain a usable Perfecto MCP binary or .app "
            f"(ignored AppleDouble / {APPLEDOUBLE_DIR} entries)."
        )
    candidates.sort(key=lambda p: (0 if p.suffix.lower() in {".exe", ""} else 1, len(str(p))))
    return candidates[0]


def stage_update_from_asset(
    asset: Dict[str, Any],
    *,
    all_assets: Optional[List[Dict[str, Any]]] = None,
) -> Path:
    """Download (and unzip if needed) into a temp directory; return install source path."""
    work = Path(tempfile.mkdtemp(prefix=f"{BINARY_NAME}-update-"))
    downloaded = download_asset(asset, work / "download")
    if all_assets:
        checksum_asset = find_checksum_asset(all_assets, asset)
        if checksum_asset and checksum_asset.get("browser_download_url"):
            checksum_path = download_asset(checksum_asset, work / "checksum")
            verify_sha256(downloaded, checksum_path.read_text(encoding="utf-8"))
    return extract_update_payload(downloaded, work / "extracted")
