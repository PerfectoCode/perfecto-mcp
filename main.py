import argparse
import json
import logging
import os
import sys
from typing import Literal, cast

from mcp.server.fastmcp import FastMCP, Icon

from config.perfecto import SECURITY_TOKEN_FILE_ENV_NAME, SECURITY_TOKEN_ENV_NAME, PERFECTO_CLOUD_NAME_ENV_NAME, \
    GITHUB
from config.token import PerfectoToken, PerfectoTokenError
from config.version import __version__, __executable__, __uvx__, get_version
from server import register_tools

PERFECTO_SECURITY_TOKEN_FILE_NAME = "perfecto-security-token.txt"
PERFECTO_SECURITY_TOKEN_FILE_PATH = os.getenv(SECURITY_TOKEN_FILE_ENV_NAME)
PERFECTO_SECURITY_TOKEN = os.getenv(SECURITY_TOKEN_ENV_NAME)
PERFECTO_CLOUD_NAME = os.getenv(PERFECTO_CLOUD_NAME_ENV_NAME)

LOG_LEVELS = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def init_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.CRITICAL)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )


def get_token() -> PerfectoToken:
    global PERFECTO_SECURITY_TOKEN_FILE_PATH, PERFECTO_SECURITY_TOKEN, PERFECTO_CLOUD_NAME, PERFECTO_SECURITY_TOKEN_FILE_NAME

    # Verify if running inside Docker container
    is_docker = os.getenv('MCP_DOCKER', 'false').lower() == 'true'
    token = None

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


def run(log_level: str = "CRITICAL"):
    token = get_token()

    instructions = """
# Perfecto MCP Server

"""

    mcp = FastMCP("perfecto-mcp", instructions=instructions,
                  log_level=cast(LOG_LEVELS, log_level))
    register_tools(mcp, token)
    mcp.run(transport="stdio")


def main():
    parser = argparse.ArgumentParser(prog="perfecto-mcp")

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}"
    )

    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Execute MCP Server"
    )

    parser.add_argument(
        "--log-level",
        default="CRITICAL",  # By default, only critical errors
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: CRITICAL = critical errors only)"
    )

    args = parser.parse_args()
    init_logging(args.log_level)

    if args.mcp:
        run(log_level=args.log_level.upper())
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

        command = "uvx" if __uvx__ else __executable__
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
