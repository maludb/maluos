"""Header-logging MCP server for the Hermes conformance suite.

Run it with the PLATFORM's venv (mcp/venv), not Hermes': the question being answered is whether
Hermes' MCP client talks to the FastMCP build our records/activity/actions servers are made of,
and whether the per-run bearer token and run-id header reach it. Same streamable-HTTP app and
the same kind of ASGI wrapper as server_common.make_app().
"""
from __future__ import annotations

import json
import os
import sys
import time

import uvicorn
from mcp.server.fastmcp import FastMCP

LOG_PATH = os.environ.get("KIT_MCP_LOG", "mcp.jsonl")
EXPECTED_TOKEN = os.environ.get("KIT_MCP_TOKEN", "")

mcp = FastMCP("bos_conformance_mcp")


def _log(row: dict) -> None:
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


@mcp.tool()
def echo_record(text: str) -> str:
    """Echo a record back. The one tool the agent is granted."""
    _log({"t": time.time(), "event": "tool", "tool": "echo_record", "text": text})
    return f"echo:{text}"


@mcp.tool()
def forbidden_tool(text: str = "") -> str:
    """A tool the agent is NOT granted. It must never be offered to the model."""
    _log({"t": time.time(), "event": "tool", "tool": "forbidden_tool", "text": text})
    return "forbidden tool ran"


def make_app():
    inner = mcp.streamable_http_app()

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return await inner(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        _log({"t": time.time(), "event": "http", "method": scope.get("method"), "path": scope.get("path"),
              "authorization": auth, "user_agent": headers.get("user-agent", ""),
              "protocol_version": headers.get("mcp-protocol-version", ""),
              "x_headers": {k: v for k, v in headers.items() if k.startswith("x-bos")}})
        if EXPECTED_TOKEN and auth != f"Bearer {EXPECTED_TOKEN}":
            body = json.dumps({"error": "unauthorized"}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body", "body": body})
            return
        await inner(scope, receive, send)

    return app


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18090
    uvicorn.run(make_app(), host="127.0.0.1", port=port, log_level="warning")
