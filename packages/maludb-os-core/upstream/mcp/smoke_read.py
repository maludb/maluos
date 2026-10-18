"""Call one READ tool on the records MCP server as a member, the way the assistant does.

  venv/bin/python smoke_read.py <member-id> <tool> ['{"param": "value"}'] [chars-to-print]

Writes nothing. Prints the tool's answer (truncated), so a module's build can show that its read
tools answer, and answer differently for different people.
"""
from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from smoke_actions import mint_token


async def main(member: int, tool: str, params: dict) -> None:
    headers = {"Authorization": f"Bearer {mint_token(member)}"}
    async with streamablehttp_client("http://127.0.0.1:8811/mcp", headers=headers) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(tool, {"params": params})
            text = res.content[0].text if res.content else ""
            try:
                rows = json.loads(text)
                size = f"{len(rows)} rows" if isinstance(rows, list) else "object"
            except ValueError:
                size = "error" if res.isError else "text"
            limit = int(sys.argv[4]) if len(sys.argv) > 4 else 420      # 4th argument: how much of the answer to print
            print(f"member {member} · {tool} · {size}: {text[:limit]}")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}))
