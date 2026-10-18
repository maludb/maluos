"""Shared runner: bearer-auth ASGI middleware + uvicorn launch for a FastMCP server.

The middleware authenticates every HTTP request against a bearer token (resolving it to a
member via mcp_resolve_token) and stashes the member context in contextvars the tools read.
Lifespan/other ASGI events pass straight through to the FastMCP app.
"""
from __future__ import annotations

import json

import uvicorn

import agent_grants
import db


def make_app(mcp, db_user_key: str, db_pw_key: str, endpoint_name: str | None = None):
    user = db.ENV[db_user_key]
    password = db.ENV[db_pw_key]
    if endpoint_name:  # an agent sees and calls only the tools it was granted on this endpoint
        agent_grants.install(mcp, endpoint_name, lambda: db.get_pool(user, password), db.request_member_id.get)
    inner = mcp.streamable_http_app()

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return await inner(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
        pool = await db.get_pool(user, password)
        ctx = await db.resolve_token(pool, token) if token else None
        if ctx is None:
            body = json.dumps({"error": "unauthorized: provide a valid MCP access token as a Bearer token"}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body", "body": body})
            return
        db.request_member_id.set(ctx[0])
        db.request_role.set(ctx[1])
        run = db.verify_run_token(token)
        db.request_run_id.set(run[1] if run else None)
        await inner(scope, receive, send)

    return app


def run(mcp, db_user_key: str, db_pw_key: str, port: int, endpoint_name: str | None = None) -> None:
    uvicorn.run(make_app(mcp, db_user_key, db_pw_key, endpoint_name), host="127.0.0.1", port=port, log_level="info")
