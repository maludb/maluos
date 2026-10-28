"""One small async client for the MaluDB API routes shared memory uses (MaluDB API 0.2.0).

Shared by the Memory MCP server and the agent runner. It takes its base URL and token as
arguments because the two callers read different secrets files — and because NOTHING ELSE may
hold that token: MaluDB namespaces are labels, not access control, so whoever holds the tenant
token reads every namespace. Scope is decided by the caller of this module, from a verified
identity, before any method here is called.
"""
from __future__ import annotations

import httpx


class MaluDBError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"MaluDB answered {status}: {message}")
        self.status, self.message = status, message


class MaluDB:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        if not base_url or not token:
            raise RuntimeError("MALUDB_API_URL and MALUDB_API_TOKEN must both be configured.")
        self._base, self._headers, self._timeout = base_url.rstrip("/"), {"Authorization": f"Bearer {token}"}, timeout

    async def _call(self, method: str, path: str, *, json=None, params=None):
        async with httpx.AsyncClient(base_url=self._base, headers=self._headers, timeout=self._timeout) as client:
            r = await client.request(method, path, json=json, params=params)
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400:
            error = body.get("error") if isinstance(body, dict) else None
            raise MaluDBError(r.status_code, (error or {}).get("message") or r.text[:200])
        return body

    async def recall(self, query: str, namespaces: list[str], subject: str | None = None, limit: int = 8) -> dict:
        payload = {"query": query, "namespaces": namespaces, "limit": limit}
        if subject:
            payload["subject"] = subject
        return await self._call("POST", "/v1/memory/recall", json=payload)

    async def profile(self, ref: str) -> dict:
        return await self._call("GET", f"/v1/principals/{ref}/profile")

    async def chat_search(self, query: str, principal: str, limit: int = 20) -> dict:
        return await self._call("GET", "/v1/chat/search", params={"q": query, "principal": principal, "limit": limit})

    async def chat_start(self, title: str, principal: str, external_ref: str, subjects: list[str] | None = None) -> int:
        body = await self._call("POST", "/v1/chat/sessions", json={
            "title": title, "principal": principal, "external_ref": external_ref, "subjects": subjects or []})
        return int(body["session"]["chat_session"]["chat_session_id"])

    async def chat_append(self, session_id: int, messages: list[dict]) -> None:
        for start in range(0, len(messages), 100):
            await self._call("POST", f"/v1/chat/sessions/{session_id}/messages", json={"messages": messages[start:start + 100]})

    async def chat_finalize(self, session_id: int) -> None:
        await self._call("POST", f"/v1/chat/sessions/{session_id}/finalize")
