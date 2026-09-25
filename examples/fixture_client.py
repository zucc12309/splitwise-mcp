"""Executable SDK stdio demo: verifies reads and creates a dry-run draft."""

import asyncio
import json
import os
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from splitwise_mcp.fixtures import PROPOSAL


async def main():
    with tempfile.TemporaryDirectory(prefix="splitwise-demo-") as directory:
        environment = {
            "PATH": os.environ["PATH"],
            "SW_OWNER": "demo-owner",
            "SW_ACCOUNT_ID": "1",
            "SW_API_KEY": "synthetic-not-a-credential",
            "SW_DATABASE": directory + "/state.sqlite",
            "SW_FIXTURE": "true",
        }
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "splitwise_mcp"], env=environment
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
            await client.initialize()
            print("Discovered tools:", len((await client.list_tools()).tools))
            for name, arguments in [
                ("get_current_user", {}),
                ("get_balances", {"group_id": 10}),
                ("preview_expense", PROPOSAL),
            ]:
                result = await client.call_tool("splitwise_" + name, arguments)
                if result.isError:
                    raise RuntimeError(result.content)
                print(json.dumps(result.structuredContent, indent=2))


asyncio.run(main())
