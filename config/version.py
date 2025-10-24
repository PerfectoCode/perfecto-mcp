import importlib.metadata
import os
import sys
import tomllib
from pathlib import Path

from config.perfecto import WEBSITE


def get_version():
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    if pyproject.exists():
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
            return data["project"]["version"]

    try:
        dist = importlib.metadata.distribution("perfecto_mcp")
        return dist.version
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def get_executable():
    if getattr(sys, 'frozen', False):
        return sys.executable
    else:
        return os.path.join(os.path.abspath(Path(__file__).parent.parent), "main.py")

def is_uvx():
    return "\\uv\\cache\\" in sys.prefix

__version__ = get_version()
__executable__ = get_executable()
__uvx__ = is_uvx()
