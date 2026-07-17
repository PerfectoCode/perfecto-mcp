"""Security helpers for HTTP endpoint allowlisting and sensitive path detection."""

import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


SENSITIVE_PATH_PREFIXES = (
    "/etc/",
    "/proc/",
    "/sys/",
    "/dev/",
    "/boot/",
    "/root/",
    "/run/secrets/",
    "/var/run/",
    "/var/db/",
    "/var/root/",
    "/var/log/",
    "/var/spool/",
    "/private/etc/",
    # macOS: /var symlinks to /private/var. Block sensitive subdirs; allow /private/var/folders/
    "/private/var/run/",
    "/private/var/db/",
    "/private/var/root/",
    "/private/var/log/",
    "/private/var/spool/",
    "/system/",
    "/library/keychains/",
    "/windows/",
    "/program files/",
    "/program files (x86)/",
    "/programdata/",
)

SENSITIVE_PATH_CONTAINS = (
    "/.ssh/",
    "/.aws/",
    "/.azure/",
    "/.gnupg/",
    "/.kube/",
    "/.docker/",
    "/.terraform/",
    "/.pulumi/",
    "/.config/gcloud/",
    "/appdata/roaming/microsoft/credentials/",
    "/appdata/roaming/gnupg/",
    "/appdata/roaming/aws/",
)

SENSITIVE_FILE_NAMES = {
    ".env",
    ".netrc",
    ".git-credentials",
    "kubeconfig",
    ".npmrc",
    ".pypirc",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "known_hosts",
    "authorized_keys",
    "credentials",
    "credentials.db",
    "terraform.tfstate",
    "terraform.tfstate.backup",
}

SENSITIVE_FILE_EXTENSIONS = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".kdbx",
    ".tfstate",
    ".tfvars",
    ".ovpn",
}

# Domains allowed for unauthenticated http_request (help documentation fetches).
ALLOWED_HTTP_REQUEST_DOMAINS = (
    "help.perfecto.io",
)


def normalize_path_for_security(file_path: str) -> str:
    return file_path.replace("\\", "/").strip().lower()


def normalize_windows_drive_prefix(file_path: str) -> str:
    if re.match(r"^[a-z]:/", file_path):
        return file_path[2:]
    return file_path


def detect_sensitive_upload_path_reason(file_path: str) -> Optional[str]:
    # Denylist of sensitive local paths/files. Available for future upload flows;
    # http_request allowlisting is the active control in this project today.
    normalized_path = normalize_path_for_security(file_path)
    normalized_without_drive = normalize_windows_drive_prefix(normalized_path)
    base_name = Path(normalized_path).name

    for prefix in SENSITIVE_PATH_PREFIXES:
        if normalized_path.startswith(prefix) or normalized_without_drive.startswith(prefix):
            return f"sensitive system path prefix '{prefix}'"

    for sensitive_fragment in SENSITIVE_PATH_CONTAINS:
        if sensitive_fragment in normalized_path:
            return f"sensitive path segment '{sensitive_fragment}'"

    if base_name in SENSITIVE_FILE_NAMES:
        return f"sensitive file name '{base_name}'"

    for sensitive_extension in SENSITIVE_FILE_EXTENSIONS:
        if base_name.endswith(sensitive_extension):
            return f"sensitive file extension '{sensitive_extension}'"

    if base_name.startswith(".env."):
        return "sensitive environment file pattern '.env.*'"

    return None


def validate_http_request_endpoint(endpoint: str) -> Optional[str]:
    parsed_url = urlparse(endpoint)

    if parsed_url.scheme != "https":
        return "Invalid endpoint scheme. Only https URLs are allowed."

    if not parsed_url.hostname:
        return "Invalid endpoint URL. Absolute URL with hostname is required."

    host = parsed_url.hostname.lower()
    if host not in ALLOWED_HTTP_REQUEST_DOMAINS:
        allowed = ", ".join(ALLOWED_HTTP_REQUEST_DOMAINS)
        return f"Endpoint host '{host}' is not allowed. Allowed hosts: {allowed}"

    return None
