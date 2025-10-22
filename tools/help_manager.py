import asyncio
import traceback
from itertools import chain
from typing import Optional, Any, Dict

import httpx
from mcp.server.fastmcp import Context
from pydantic import Field

from config.perfecto import TOOLS_PREFIX, SUPPORT_MESSAGE, get_real_devices_extended_commands_help_url, \
    get_real_devices_extended_command_base_help_url
from config.token import PerfectoToken
from formatters.help import format_list_real_devices_extended_commands_info, \
    format_read_real_devices_extended_command_info, format_help_info
from models.manager import Manager
from models.result import BaseResult
from tools.utils import http_request, convert_js_to_py_dict


class HelpManager(Manager):
    def __init__(self, token: Optional[PerfectoToken], ctx: Context):
        super().__init__(token, ctx)
        self.help_tree = None

    async def _load_help_tree(self):
        help_index_url = "https://help.perfecto.io/perfecto-help/Data/Tocs/perfecto_help.js"
        help_index_response = await http_request("GET", endpoint=help_index_url)

        help_index_response.result = convert_js_to_py_dict(help_index_response.result)

        num_chunks = help_index_response.result.get("numchunks", 6)
        chunk_prefix = help_index_response.result.get("prefix", "perfecto_help_Chunk")

        help_chunk_urls = []

        for i in range(num_chunks):
            help_chunk_url = f"https://help.perfecto.io/perfecto-help/Data/Tocs/{chunk_prefix}{i}.js"
            help_chunk_urls.append(help_chunk_url)

        async def fetch_chunk(chunk_url):
            help_chunk_response = await http_request("GET", endpoint=chunk_url)
            help_chunk_response.result = convert_js_to_py_dict(help_chunk_response.result)
            help_content = []
            for url, content in help_chunk_response.result.items():
                help_item = {"title": content.get("t", [""])[0],
                             "help_id": url.replace("/content/", "").replace(".htm", "")}
                if help_item.get("help_id") == "___" or help_item.get("help_id").startswith("release-notes/"):
                    continue
                help_content.append(help_item)
            return help_content

        tasks = [fetch_chunk(url) for url in help_chunk_urls]
        results = await asyncio.gather(*tasks)

        merged = list(chain.from_iterable(results))

        help_tree = {}
        for item in merged:
            sections = item.get("help_id").split("/")
            category = sections[0]
            if len(sections) > 2:
                sub_category = sections[1]
                new_id = "/".join(sections[2:])
            else:
                sub_category = ""
                new_id = "/".join(sections[1:])

            item["help_id"] = new_id
            if category not in help_tree:
                help_tree[category] = {}
            if sub_category not in help_tree[category]:
                help_tree[category][sub_category] = []
            help_tree[category][sub_category].append(item)

        self.help_tree = help_tree

    async def list_help_categories(self) -> BaseResult:
        if self.help_tree is None:
            await self._load_help_tree()
        categories = {}
        for key in self.help_tree.keys():
            categories[key] = list(self.help_tree[key].keys())
        return BaseResult(
            result=categories,
            info=["A list of subcategories is provided for each category"]
        )

    async def list_help_category_content(self, category_id: str, sub_category_id: str) -> BaseResult:
        if self.help_tree is None:
            await self._load_help_tree()
        if category_id in self.help_tree.keys() and sub_category_id in self.help_tree[category_id]:
            return BaseResult(
                result=self.help_tree[category_id][sub_category_id]
            )
        else:
            return BaseResult(warning=[f"Category '{category_id}' and subcategory '{sub_category_id}' not found."])

    @staticmethod
    async def read_help_info(category_id: str, sub_category_id: str, help_id: str) -> BaseResult:
        help_base_url = "https://help.perfecto.io/perfecto-help/content/"
        help_url = f"{help_base_url}{category_id}/"
        if sub_category_id != "":
            help_url += f"{sub_category_id}/"
        help_url += f"{help_id}.htm"
        return await http_request("GET", endpoint=help_url, result_formatter=format_help_info,
                                  result_formatter_params={"base_url": help_url})

    async def list_real_devices_extended_commands(self) -> BaseResult:
        real_devices_extended_commands_help_url = get_real_devices_extended_commands_help_url()
        commands_result = await http_request("GET", endpoint=real_devices_extended_commands_help_url,
                                  result_formatter=format_list_real_devices_extended_commands_info)

        # Try to get also all the one level inside the category perfecto and sub category automation-testing
        category_id = "perfecto"
        sub_category_id = "automation-testing"
        sub_pages = await self.list_help_category_content(category_id, sub_category_id)
        return BaseResult(
            result={
                "commands": commands_result.result,
                "additional_help_pages": {
                    "category_id": category_id,
                    "sub_category_id": sub_category_id,
                    "help_pages": sub_pages
                }
            }
        )

    @staticmethod
    async def read_real_devices_extended_command_info(command_id: str) -> BaseResult:
        real_devices_extended_command_help_url = get_real_devices_extended_command_base_help_url()
        real_devices_extended_command_help_url = f"{real_devices_extended_command_help_url}{command_id}.htm"
        return await http_request("GET", endpoint=real_devices_extended_command_help_url,
                                  result_formatter=format_read_real_devices_extended_command_info,
                                  result_formatter_params={"base_url": real_devices_extended_command_help_url})


def register(mcp, token: Optional[PerfectoToken]):
    @mcp.tool(
        name=f"{TOOLS_PREFIX}_help",
        description="""
Operations on documentation and help information.
Actions:
- list_help_categories: List all category_ids and for each of them list their subcategory_ids.
- list_help_category_content: List all help_id list related with a category_id and subcategory_id.
    args(dict): Dictionary with the following required parameters:
        category_id (str): The category id.
        sub_category_id (str): The subcategory id.
- read_help_info: Read the content of a help_id providing category_id, subcategory_id and help_id
    args(dict): Dictionary with the following required parameters:
        category_id (str): The category id.
        sub_category_id (str): The subcategory id.
        help_id (str): The help id.
- list_real_devices_extended_commands: Perfecto provides support for extended RemoteWebDriver commands. You can use these commands as extensions to the default SDK. Perfecto extensions are also known as function references (FR).
- read_real_devices_extended_command_info: Read the detailed command information.
    args(dict): Dictionary with the following required parameters:
        command_id (str): The command id.
Hints:
- Always generates the url attributes as a link in markdown format (like command_url).
"""
    )
    async def help_main(
            action: str = Field(description="The action id to execute"),
            args: Dict[str, Any] = Field(description="Dictionary with parameters"),
            ctx: Context = Field(description="Context object providing access to MCP capabilities")
    ) -> BaseResult:

        help_manager = HelpManager(token, ctx)
        try:
            match action:
                case "list_help_categories":
                    return await help_manager.list_help_categories()
                case "list_help_category_content":
                    return await help_manager.list_help_category_content(args.get("category_id", "home"),
                                                                         args.get("sub_category_id", ""))
                case "read_help_info":
                    return await help_manager.read_help_info(args.get("category_id", "home"),
                                                             args.get("sub_category_id", ""), args.get("help_id", ""))
                case "list_real_devices_extended_commands":
                    return await help_manager.list_real_devices_extended_commands()
                case "read_real_devices_extended_command_info":
                    return await help_manager.read_real_devices_extended_command_info(args["command_id"])
                case _:
                    return BaseResult(
                        error=f"Action {action} not found in help manager tool"
                    )
        except httpx.HTTPStatusError:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}"
            )
        except Exception:
            return BaseResult(
                error=f"Error: {traceback.format_exc()}\n{SUPPORT_MESSAGE}"
            )
