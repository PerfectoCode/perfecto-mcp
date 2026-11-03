"""Environment helpers for Perfecto MCP tunables.

Names are read as ``PERFECTO_MCP_<NAME>`` (for example
``PERFECTO_MCP_MAX_PARALLEL_TASKS``).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

ENV_PREFIX = "PERFECTO_MCP_"


def _raw(name: str) -> Optional[str]:
    value = os.getenv(f"{ENV_PREFIX}{name}")
    if value is None or not value.strip():
        return None
    return value.strip()


def env_str(name: str, default: str = "") -> str:
    value = _raw(name)
    return default if value is None else value


def env_int(name: str, default: int, *, minimum: Optional[int] = None) -> int:
    value = _raw(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        logger.warning("Invalid %s%s=%r; using default %s", ENV_PREFIX, name, value, default)
        return default
    if minimum is not None and parsed < minimum:
        logger.warning(
            "%s%s=%s is below %s; using default %s", ENV_PREFIX, name, parsed, minimum, default,
        )
        return default
    return parsed


def env_float(name: str, default: float, *, minimum: Optional[float] = None) -> float:
    value = _raw(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        logger.warning("Invalid %s%s=%r; using default %s", ENV_PREFIX, name, value, default)
        return default
    if minimum is not None and parsed < minimum:
        logger.warning(
            "%s%s=%s is below %s; using default %s", ENV_PREFIX, name, parsed, minimum, default,
        )
        return default
    return parsed


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def env_bool(name: str, default: bool) -> bool:
    value = _raw(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    logger.warning("Invalid %s%s=%r; using default %s", ENV_PREFIX, name, value, default)
    return default
