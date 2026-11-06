#!/usr/bin/env python3
"""Build script for creating PyInstaller binary."""
import os
import platform
import plistlib
import shutil
import string
import subprocess
import tomllib
from datetime import date
from pathlib import Path

import PyInstaller.__main__

sep = os.pathsep


def clean_build():
    build_dir = Path('build')
    if build_dir.exists():
        shutil.rmtree(build_dir)


def read_project_metadata() -> dict:
    pyproject = Path(__file__).parent / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    return data["project"]


def build_version_file():
    project = read_project_metadata()
    version = project["version"]
    name = project["name"]
    description = project["description"]

    nums = tuple(int(x) for x in version.split(".")) + (0,) * (4 - len(version.split(".")))

    TEMPLATE = f"""
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={nums},
    prodvers={nums},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'Perfecto'),
        StringStruct('FileDescription', '{description}'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', '{name}'),
        StringStruct('LegalCopyright', '© {date.today().year} Perfecto'),
        StringStruct('OriginalFilename', '{name}.exe'),
        StringStruct('ProductName', 'Perfecto MCP'),
        StringStruct('ProductVersion', '{version}')])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

    with open("version_info.txt", "w", encoding="utf-8") as f:
        f.write(TEMPLATE.strip())


def normalize_architecture(arch: str) -> str:
    if arch in ['x86_64', 'amd64']:
        return 'amd64'
    elif arch in ['aarch64', 'arm64']:
        return 'arm64'
    elif arch.startswith('arm'):
        return 'arm64'
    return arch


def normalize_system_name(system: str) -> str:
    return "macos" if system == 'darwin' else system


def get_binary_name(system: str, arch: str) -> str:
    suffix = '.exe' if system == 'windows' else ''
    return f'perfecto-mcp-{system}-{arch}{suffix}'


def get_icon_file(system: str) -> str:
    return 'app.icns' if system == 'macos' else 'app.ico'


APP_EXECUTABLE = "perfecto-mcp"
COLLECT_DIR_NAME = "perfecto-mcp"


def bundle_mode(system: str) -> str:
    """macOS ships a PyInstaller folder so launch skips the one-file unpack."""
    return "onedir" if system == "macos" else "onefile"


def hiddenimports() -> list[str]:
    return [
        "tools.ai_scriptless",
        "tools.ai_scriptless.commands",
        "tools.ai_scriptless.elements",
        "tools.ai_scriptless.item_key",
        "tools.ai_scriptless.persistence",
        "tools.ai_scriptless.script",
        "tools.ai_scriptless.step_path",
        "tools.ai_scriptless.tree",
        "tools.ai_scriptless.variables",
        "opentelemetry.sdk.trace",
        "opentelemetry.sdk.trace.export",
        "opentelemetry.sdk.resources",
        "opentelemetry.sdk.metrics",
        "opentelemetry.sdk.metrics.export",
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
        "opentelemetry.exporter.otlp.proto.grpc.metric_exporter",
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "opentelemetry.exporter.otlp.proto.http.metric_exporter",
        "opentelemetry.propagate",
    ]


def pyinstaller_args(name: str, icon: str) -> list[str]:
    return [
        'main.py',
        '--onefile',
        '--version-file=version_info.txt',
        f'--add-data=pyproject.toml{sep}.',
        f'--add-data=resources{sep}resources',
        f'--name={name}',
        f'--icon={icon}',
        '--clean',
        '--noconfirm',
        *[f'--hidden-import={module}' for module in hiddenimports()],
        '--collect-submodules=opentelemetry',
        '--collect-all=grpc',
        # Streamable HTTP transport: uvicorn resolves its loop/protocol
        # implementations by name at runtime, so PyInstaller cannot see them.
        '--collect-submodules=uvicorn',
    ]


MACOS_SPEC_TEMPLATE = Path(__file__).parent / "packaging" / "macos.spec.template"


def macos_spec(arch: str, icon: str, version: str) -> str:
    """Render the macOS onedir spec from packaging/macos.spec.template."""
    template = string.Template(MACOS_SPEC_TEMPLATE.read_text(encoding="utf-8"))
    return template.substitute(
        hiddenimports=", ".join(repr(name) for name in hiddenimports()),
        executable_name=repr(APP_EXECUTABLE),
        icon=repr(icon),
        collect_name=repr(COLLECT_DIR_NAME),
        app_name=repr(f"perfecto-mcp-{arch}.app"),
        version=repr(version),
    )


def run_pyinstaller(name: str, icon: str):
    PyInstaller.__main__.run(pyinstaller_args(name, icon))


def run_macos_bundle(arch: str, icon: str, dist_dir: Path):
    version = read_project_metadata()["version"]
    spec_path = Path("perfecto-mcp-macos.spec")
    spec_path.write_text(macos_spec(arch, icon, version), encoding="utf-8")
    try:
        PyInstaller.__main__.run([str(spec_path), "--clean", "--noconfirm"])
    finally:
        spec_path.unlink(missing_ok=True)
        clean_build()
    finalize_macos_app(arch, dist_dir)


def build():
    clean_build()

    system = normalize_system_name(platform.system().lower())
    arch = normalize_architecture(platform.machine().lower())
    name = get_binary_name(system, arch)
    icon = get_icon_file(system)
    dist_dir = Path("dist")

    if bundle_mode(system) == "onedir":
        run_macos_bundle(arch, icon, dist_dir)
    else:
        run_pyinstaller(name, icon)
        clean_build()
        if system == "linux":
            create_sha256_checksum(name, dist_dir=dist_dir)


def create_launcher_script(launcher_path: Path):
    launcher_content = """#!/bin/bash
set -e

BIN_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$BIN_DIR/perfecto-mcp"

if [ -t 1 ]; then
  exec "$BIN" "$@"
else
  open -a Terminal "$BIN"
fi
"""
    with open(launcher_path, "w", encoding="utf-8") as f:
        f.write(launcher_content)
    os.chmod(launcher_path, 0o755)


def configure_launcher_plist(plist_path: Path) -> None:
    """Point the bundle at launcher.sh so a double-click opens Terminal."""
    with plist_path.open("rb") as fh:
        info = plistlib.load(fh)
    info["CFBundleExecutable"] = "launcher.sh"
    info["CFBundleName"] = "Perfecto MCP"
    info["CFBundleDisplayName"] = "Perfecto MCP"
    info["CFBundleIdentifier"] = "com.perfecto.mcp"
    info.pop("LSBackgroundOnly", None)
    with plist_path.open("wb") as fh:
        plistlib.dump(info, fh)


def codesign_command(app_path: Path, identity: str | None = None) -> list[str]:
    """Sign the .app and every nested Mach-O produced by the onedir bundle.

    ``--deep`` is required. Signing only the outer bundle leaves the libraries
    in ``Contents/Frameworks`` unsigned. Set ``MACOS_CODESIGN_IDENTITY`` to a
    Developer ID; otherwise the bundle is ad-hoc signed.
    """
    if identity is None:
        identity = os.environ.get("MACOS_CODESIGN_IDENTITY", "-").strip() or "-"
    return [
        "codesign",
        "--force",
        "--deep",
        "--sign",
        identity,
        str(app_path),
    ]


def sign_app_bundle(app_path: Path) -> None:
    subprocess.run(codesign_command(app_path), check=True)
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app_path)],
        check=True,
    )


def finalize_macos_app(arch: str, dist_dir: Path) -> None:
    app_name = f"perfecto-mcp-{arch}.app"
    app_path = dist_dir / app_name
    macos_path = app_path / "Contents" / "MacOS"
    executable = macos_path / APP_EXECUTABLE
    if not executable.is_file():
        raise FileNotFoundError(f"Bundle executable not found: {executable}")

    create_launcher_script(macos_path / "launcher.sh")
    configure_launcher_plist(app_path / "Contents" / "Info.plist")

    collect_dir = dist_dir / COLLECT_DIR_NAME
    if collect_dir.exists():
        shutil.rmtree(collect_dir)

    sign_app_bundle(app_path)
    print(f"Created {app_name} in {dist_dir}")


def create_sha256_checksum(binary_name: str, dist_dir: Path):
    binary_path = dist_dir / binary_name
    checksum_path = dist_dir / f"{binary_name}.sha256"
    
    if not binary_path.exists():
        raise FileNotFoundError(f"Binary not found: {binary_path}")
    
    with open(checksum_path, "w") as f:
        subprocess.run(
            ["sha256sum", binary_name],
            cwd=dist_dir,
            stdout=f,
            check=True,
        )
    
    print(f"Created {checksum_path.name} in {dist_dir}")


if __name__ == "__main__":
    build_version_file()
    build()
