"""
Tests for the memory-maintenance endpoints (lifecycle / consolidation / scoring proxies).

No live Postgres: registration tests assert 401 without auth; behaviour tests use a temp
SQLite auth store + mocked tenant connection and patch the db helpers imported into
app.routers.memory_maintenance.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

_client = TestClient(app, raise_server_exceptions=False)

_AUTH_PATHS = [
    ("POST", "/v1/memory/consolidate"),
    ("POST", "/v1/memory/lifecycle"),
    ("POST", "/v1/memory/staleness"),
    ("POST", "/v1/memory/score"),
    ("POST", "/v1/memory/reinforcement"),
    ("GET", "/v1/memory/retention-candidates?object_type=memory"),
]


class TestMemoryMaintenanceRegistered:
    @pytest.mark.parametrize("method,path", _AUTH_PATHS)
    def test_missing_auth_returns_401(self, method: str, path: str):
        response = _client.request(method, path)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_missing"


_TOKEN_BODY = "maint_test_token"
_TOKEN = f"malu_{_TOKEN_BODY}"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


@pytest.fixture()
def store(tmp_path: Path):
    from app.auth_store import AuthStore

    s = AuthStore(str(tmp_path / "test_auth.db"))
    s.init_db()
    s.connection.execute(
        """INSERT INTO users (token_hash, token_prefix, user_id, role, pg_dbname, pg_user, pg_password)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (hashlib.sha256(_TOKEN_BODY.encode()).hexdigest(), "maint_test_", 7, "executor", "db", "u", "p"),
    )
    s.connection.commit()
    return s


@pytest.fixture()
def client(store) -> TestClient:
    with patch("app.auth.get_auth_store", return_value=store), patch("app.auth.TenantConnection") as tc:
        tc.return_value.connect.return_value = MagicMock()
        yield TestClient(app, raise_server_exceptions=False)


class TestConsolidate:
    def test_501_when_core_function_missing(self, client: TestClient):
        with patch("app.routers.memory_maintenance.db_one", return_value={"ok": False}):
            res = client.post(
                "/v1/memory/consolidate",
                headers=_HEADERS,
                json={"memory_ids": [1, 2], "kind": "lesson", "title": "t", "summary": "s"},
            )
        assert res.status_code == 501
        assert res.json()["error"]["code"] == "consolidate_memories_unavailable"

    def test_returns_new_memory_id(self, client: TestClient):
        with (
            patch("app.routers.memory_maintenance.db_one", return_value={"ok": True}),
            patch("app.routers.memory_maintenance.db_tx_core", return_value={"memory_id": 123}),
        ):
            res = client.post(
                "/v1/memory/consolidate",
                headers=_HEADERS,
                json={"memory_ids": [1, 2, 3], "kind": "lesson", "title": "t", "summary": "s"},
            )
        assert res.status_code == 201
        assert res.json() == {"consolidated_into_memory_id": 123}

    def test_400_on_missing_memory_ids(self, client: TestClient):
        res = client.post("/v1/memory/consolidate", headers=_HEADERS, json={"kind": "lesson", "title": "t"})
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "missing_field"


class TestLifecycleAndScore:
    def test_lifecycle_rejects_unknown_object_type(self, client: TestClient):
        res = client.post(
            "/v1/memory/lifecycle",
            headers=_HEADERS,
            json={"object_type": "banana", "object_id": 1, "state": "archived"},
        )
        assert res.status_code == 400

    def test_lifecycle_applies_state(self, client: TestClient):
        with (
            patch("app.routers.memory_maintenance.db_one", return_value={"ok": True}),
            patch("app.routers.memory_maintenance.db_tx_core", return_value={"ok": None}),
        ):
            res = client.post(
                "/v1/memory/lifecycle",
                headers=_HEADERS,
                json={"object_type": "memory", "object_id": 5, "state": "archived", "reason": "old"},
            )
        assert res.status_code == 200
        assert res.json() == {"object_type": "memory", "object_id": 5, "state": "archived"}

    def test_score_returns_id(self, client: TestClient):
        with (
            patch("app.routers.memory_maintenance.db_one", return_value={"ok": True}),
            patch("app.routers.memory_maintenance.db_tx_core", return_value={"maut_score_id": 9}),
        ):
            res = client.post(
                "/v1/memory/score",
                headers=_HEADERS,
                json={
                    "object_type": "fact",
                    "object_id": 5,
                    "category": "contradiction_status",
                    "subscore": 0.2,
                    "evaluator_name": "agent",
                },
            )
        assert res.status_code == 201
        assert res.json() == {"maut_score_id": 9}
