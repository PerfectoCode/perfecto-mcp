import argparse
import json
import logging
import os
import sys
from typing import Literal, cast

# Patch MCP ArgModelBase so tools with an "arguments" param receive the full payload
# when the client sends {"action": "x", "key": "value"} instead of {"arguments": {...}}
from mcp.server.fastmcp.utilities import func_metadata
from pydantic import model_validator

_OriginalArgModelBase = func_metadata.ArgModelBase


class _PatchedArgModelBase(_OriginalArgModelBase):
    @model_validator(mode="before")
    @classmethod
    def _wrap_root_as_arguments(cls, data: object) -> object:
        if isinstance(data, dict) and "arguments" not in data:
            return {"arguments": data}
        return data


func_metadata.ArgModelBase = _PatchedArgModelBase

from mcp.server.fastmcp import FastMCP, Icon

from config.auth import run_streamable_http
from config.perfecto import SECURITY_TOKEN_FILE_ENV_NAME, SECURITY_TOKEN_ENV_NAME, PERFECTO_CLOUD_NAME_ENV_NAME, \
    GITHUB
from config.runtime import build_runtime, resolve_http_bind_settings
from config.token import PerfectoToken, PerfectoTokenError
from config.version import __version__, __executable__, __bundle__, __uvx__, get_version
from server import register_tools
from telemetry import init_telemetry

PERFECTO_SECURITY_TOKEN_FILE_NAME = "perfecto-security-token.txt"
PERFECTO_SECURITY_TOKEN_FILE_PATH = os.getenv(SECURITY_TOKEN_FILE_ENV_NAME)
PERFECTO_SECURITY_TOKEN = os.getenv(SECURITY_TOKEN_ENV_NAME)
PERFECTO_CLOUD_NAME = os.getenv(PERFECTO_CLOUD_NAME_ENV_NAME)

LOG_LEVELS = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
MCP_TRANSPORTS = ("stdio", "http", "docker")


def init_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.CRITICAL)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )


def get_token() -> PerfectoToken:
    global PERFECTO_SECURITY_TOKEN_FILE_PATH, PERFECTO_SECURITY_TOKEN, PERFECTO_CLOUD_NAME, PERFECTO_SECURITY_TOKEN_FILE_NAME

    # Verify if running inside Docker container
    is_docker = os.getenv('MCP_DOCKER', 'false').lower() == 'true'
    token = None

    if sys.platform == "darwin" and __bundle__.endswith(".app"):
        local_security_token_file = os.path.join(os.path.dirname(__bundle__), PERFECTO_SECURITY_TOKEN_FILE_NAME)
    else:
        local_security_token_file = os.path.join(os.path.dirname(__executable__), PERFECTO_SECURITY_TOKEN_FILE_NAME)
    if not PERFECTO_SECURITY_TOKEN_FILE_PATH and os.path.exists(local_security_token_file):
        PERFECTO_SECURITY_TOKEN_FILE_PATH = local_security_token_file

    if PERFECTO_SECURITY_TOKEN_FILE_PATH:
        try:
            token = PerfectoToken.from_file(PERFECTO_SECURITY_TOKEN_FILE_PATH, PERFECTO_CLOUD_NAME)
        except PerfectoTokenError:
            logging.debug("Failed to load perfecto security token", exc_info=True)
            # Token file exists but is invalid - this will be handled by individual tools
            pass
        except Exception:
            # Other errors (file not found, permissions, etc.) - also handled by tools
            logging.debug("Failed to load perfecto security token", exc_info=True)
            pass
    elif is_docker:
        token = PerfectoToken(PERFECTO_SECURITY_TOKEN, PERFECTO_CLOUD_NAME)

    return token


def resolve_mcp_transport(raw_cli_transport: str) -> str:
    """
    Resolve transport with precedence: CLI > PERFECTO_MCP_TRANSPORT > stdio.

    `raw_cli_transport` comes from argparse `--mcp`:
    - empty string means `--mcp` was provided without an explicit value
    - non-empty string means an explicit CLI transport was provided
    """
    raw_cli_transport = raw_cli_transport.strip()

    if raw_cli_transport:
        candidate = raw_cli_transport
        source = "CLI --mcp"
    else:
        candidate = os.getenv("PERFECTO_MCP_TRANSPORT", "").strip()
        source = "PERFECTO_MCP_TRANSPORT"

    if not candidate:
        return "stdio"

    normalized = candidate.lower()
    if normalized not in MCP_TRANSPORTS:
        allowed = ", ".join(MCP_TRANSPORTS)
        raise ValueError(
            f"Invalid MCP transport '{candidate}' from {source}. "
            f"Valid values: {allowed}."
        )
    return normalized


def to_wire_transport(logical_transport: str) -> Literal["stdio", "streamable-http"]:
    """Map CLI/logical transport (stdio|http|docker) to FastMCP wire transport."""
    return "streamable-http" if logical_transport == "http" else "stdio"


def build_mcp_server(
        log_level: str = "CRITICAL",
        transport: str = "stdio",
) -> tuple[FastMCP, str]:
    """
    Build FastMCP + auth wiring for a logical CLI transport (stdio|http|docker).

    Returns ``(mcp, wire_transport)`` where ``wire_transport`` is the FastMCP
    transport name (``stdio`` or ``streamable-http``).
    """
    init_telemetry("perfecto-mcp", __version__)
    # docker and stdio share process-lifetime credentials; http uses Bearer per request.
    wire_transport = to_wire_transport(transport)
    app_runtime = build_runtime(
        wire_transport,
        startup_token=get_token() if wire_transport == "stdio" else None,
    )
    instructions = """
# Perfecto MCP Server

"""
    mcp_kwargs: dict = {
        "instructions": instructions,
        "log_level": cast(LOG_LEVELS, log_level),
    }
    if transport == "http":
        bind = resolve_http_bind_settings()
        mcp_kwargs.update(
            host=bind.host,
            port=bind.port,
            streamable_http_path=bind.streamable_http_path,
            stateless_http=False,
        )
    mcp = FastMCP("perfecto-mcp", **mcp_kwargs)
    register_tools(mcp, app_runtime)
    return mcp, wire_transport


def run(log_level: str = "CRITICAL", transport: str = "stdio"):
    mcp, runtime_transport = build_mcp_server(
        log_level=log_level,
        transport=transport,
    )
    if runtime_transport == "stdio":
        mcp.run(transport=runtime_transport)
    else:
        # Hosted HTTP requires Bearer auth middleware around the ASGI app.
        run_streamable_http(mcp)


def main():
    parser = argparse.ArgumentParser(
        prog="perfecto-mcp",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}"
    )

    parser.add_argument(
        "--mcp",
        nargs="?",
        const="",
        metavar="TRANSPORT",
        help=(
            "Execute MCP Server. Optional TRANSPORT values: stdio, http, docker.\n"
            "Resolution precedence: CLI > PERFECTO_MCP_TRANSPORT > stdio."
        ),
    )

    parser.add_argument(
        "--log-level",
        default="CRITICAL",  # By default, only critical errors
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: CRITICAL = critical errors only)"
    )

    args = parser.parse_args()
    
    if args.mcp is not None:
        try:
            transport = resolve_mcp_transport(args.mcp)
            if transport == "docker":
                os.environ["MCP_DOCKER"] = "true"
            elif transport == "http":
                os.environ["MCP_DOCKER"] = "false"
            init_logging(args.log_level)
            run(log_level=args.log_level.upper(), transport=transport)
        except ValueError as e:
            parser.error(str(e))
    else:

        logo_ascii = (
            "  _____           __          _        \n"
            " |  __ \         / _|        | |       \n"
            " | |__) |__ _ __| |_ ___  ___| |_ ___  \n"
            " |  ___/ _ \ '__|  _/ _ \/ __| __/ _ \ \n"
            " | |  |  __/ |  | ||  __/ (__| || (_) |\n"
            " |_|   \___|_|  |_| \___|\___|\__\___/ \n"
            "                                       \n"
            f" Perfecto MCP Server v{__version__} \n"
        )
        print(logo_ascii)

        if PERFECTO_CLOUD_NAME is None:
            perfecto_environment_str = "Set the environment value here"
        else:
            perfecto_environment_str = f"{PERFECTO_CLOUD_NAME}"

        if sys.platform == "darwin" and __bundle__.endswith(".app"):
            command_path = os.path.join(__bundle__, "Contents", "MacOS", "perfecto-mcp")
        else:
            command_path = __executable__
        command = "uvx" if __uvx__ else command_path
        args = ["--mcp"]
        if __uvx__:
            args = [
                "--from", f"git+{GITHUB}.git@v{get_version()}",
                "-q", "perfecto-mcp",
                "--mcp"
            ]

        config_dict = {
            "Perfecto MCP": {
                "command": f"{command}",
                "args": args,
                "env": {
                    f"{PERFECTO_CLOUD_NAME_ENV_NAME}": f"{perfecto_environment_str}"
                }
            }
        }

        print(" MCP Server Configuration:\n")
        print(" In your tool with MCP server support, locate the MCP server configuration file")
        print(" and add the following server to the server list.\n")

        json_str = json.dumps(config_dict, ensure_ascii=False, indent=4)
        print("\n".join(json_str.split("\n")[1:-1]) + "\n")

        if not get_token():
            print(" [X] Perfecto Security Token Key not configured or Perfecto Environment not configured.")
            print(" ")
            print(
                f" Copy the Perfecto Security Token Key in a text file ({PERFECTO_SECURITY_TOKEN_FILE_NAME} to the same location of this executable.")
            print(f" Make sure you have the '{PERFECTO_CLOUD_NAME_ENV_NAME}' environment variable set correctly.")
            print(" ")
            print(" How to obtain the Security Token:")
            print(
                " https://help.perfecto.io/perfecto-help/content/perfecto/automation-testing/generate_security_tokens.htm")
        else:
            print(" [OK] Perfecto Security Token Key configured correctly.")
        print(" ")
        print(" There are configuration alternatives, if you want to know more:")
        print(" https://github.com/PerfectoCode/perfecto-mcp/")
        print(" ")

        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
