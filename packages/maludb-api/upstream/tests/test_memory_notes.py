"""
Tests for the memory_notes router — endpoint registration and the seeded
query_parse catalog rows.

Tests that don't need a live Postgres connection: the endpoint is mounted
(401 not 404 without auth) and the query_parse task is seeded for every
chat model.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.llm_catalog import TASKS, seed_rows
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


class TestMemoryNotesRouterRegistered:
    def test_missing_auth_returns_401(self):
        response = client.get("/v1/memory/notes", params={"subject_like": "ubuntu"})
        assert response.status_code == 401, f"GET /v1/memory/notes returned {response.status_code}, expected 401"
        data = response.json()
        assert data["error"]["code"] == "auth_missing"

    def test_unknown_method_is_405(self):
        response = client.post("/v1/memory/notes")
        assert response.status_code == 405


class TestQueryParseCatalog:
    def test_query_parse_is_a_task(self):
        assert "query_parse" in TASKS

    def test_every_chat_model_has_a_query_parse_row(self):
        rows = seed_rows()
        by_task: dict[str, set[str]] = {}
        for r in rows:
            by_task.setdefault(r["task"], set()).add(r["model_name"])
        assert by_task["query_parse"] == by_task["extract"]
        for r in rows:
            if r["task"] == "query_parse":
                assert r["system_prompt"], f"{r['model_name']} query_parse row has no prompt"
                assert r["max_tokens"] == 256
