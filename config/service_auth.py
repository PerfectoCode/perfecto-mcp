"""How Perfecto MCP authenticates to the hosted storage service."""
from typing import Optional

from config.env import env_str

# End-user credential of the current call. The storage service treats it as opaque.
CREDENTIAL_HEADER = "X-Perfecto-Credential"


def service_caller_token() -> str:
    """MCP caller identity for the hosted storage service (``PERFECTO_MCP_STORAGE_CALLER_TOKEN``)."""
    return env_str("STORAGE_CALLER_TOKEN")


def service_headers(caller_token: Optional[str], credential: Optional[str] = None) -> dict[str, str]:
    """Headers for a hosted-service request: caller identity, plus the end-user credential if any."""
    headers: dict[str, str] = {}
    if caller_token:
        headers["Authorization"] = f"Bearer {caller_token}"
    if credential:
        headers[CREDENTIAL_HEADER] = credential
    return headers
