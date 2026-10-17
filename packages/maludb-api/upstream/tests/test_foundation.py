"""
Tests for the foundation layer — errors, sql_log, auth_store, and health endpoint.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.errors import APIError
from app.sql_log import SqlTracer

# ---------------------------------------------------------------------------
# APIError
# ---------------------------------------------------------------------------

class TestAPIError:
    def test_raises_with_correct_shape(self):
        with pytest.raises(APIError) as exc_info:
            raise APIError("not_found", "Thing not found.", 404)
        err = exc_info.value
        assert err.code == "not_found"
        assert err.message == "Thing not found."
        assert err.status == 404

    def test_default_status_is_400(self):
        err = APIError("bad_request", "Oops.")
        assert err.status == 400


# ---------------------------------------------------------------------------
# SqlTracer
# ---------------------------------------------------------------------------

class TestSqlTracer:
    def test_collects_queries(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Point LOG_DIR to a temp directory so file writes succeed
        monkeypatch.setattr("app.config.LOG_DIR", str(tmp_path))
        tracer = SqlTracer()
        tracer.endpoint = "test"
        tracer.method = "GET"
        tracer.uri = "/v1/test"
        tracer.user_id = 42

        tracer.log("SELECT 1", [], 1, 0.5)
        tracer.log("SELECT id FROM foo WHERE bar = %s", ["baz"], 3, 1.2)

        assert len(tracer.queries) == 2
        assert tracer.queries[0]["sql"] == "SELECT 1"
        assert tracer.queries[0]["rows"] == 1
        assert tracer.queries[0]["dur_ms"] == 0.5
        assert tracer.queries[1]["params"] == ["baz"]
        assert tracer.queries[1]["rows"] == 3

    def test_writes_log_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("app.config.LOG_DIR", str(tmp_path))
        tracer = SqlTracer()
        tracer.endpoint = "subjects"
        tracer.method = "POST"
        tracer.uri = "/v1/subjects"
        tracer.user_id = 7

        tracer.log("INSERT INTO foo VALUES (%s)", ["hello"], 1, 2.3)

        log_file = tmp_path / "sql.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "subjects" in content
        assert "INSERT INTO foo VALUES (%s)" in content
        assert "user=7" in content


# ---------------------------------------------------------------------------
# AuthStore
# ---------------------------------------------------------------------------

class TestAuthStore:
    def _make_store(self) -> tuple:
        """Create a temporary AuthStore with test data."""
        from app.auth_store import AuthStore

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        store = AuthStore(tmp.name)
        store.init_db()
        return store, tmp.name

    def test_resolve_token_found(self):
        store, db_path = self._make_store()
        try:
            token_body = "test_secret_123"
            token_hash = hashlib.sha256(token_body.encode()).hexdigest()
            store.connection.execute(
                """
                INSERT INTO users (token_hash, token_prefix, user_id, role, pg_dbname, pg_user, pg_password)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (token_hash, "malu_test_", 42, "executor", "testdb", "testuser", "testpass"),
            )
            store.connection.commit()

            result = store.resolve_token(token_hash)
            assert result is not None
            assert result["user_id"] == 42
            assert result["role"] == "executor"
            assert result["pg_dbname"] == "testdb"
            assert result["pg_user"] == "testuser"
            assert result["pg_password"] == "testpass"
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_resolve_token_unknown(self):
        store, db_path = self._make_store()
        try:
            result = store.resolve_token("nonexistent_hash_value")
            assert result is None
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_resolve_token_expired(self):
        store, db_path = self._make_store()
        try:
            token_body = "expired_token"
            token_hash = hashlib.sha256(token_body.encode()).hexdigest()
            store.connection.execute(
                """
                INSERT INTO users (token_hash, token_prefix, user_id, role, pg_dbname, pg_user, pg_password, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (token_hash, "malu_exp_", 99, "viewer", "expdb", "expuser", "exppass", "2020-01-01T00:00:00Z"),
            )
            store.connection.commit()

            result = store.resolve_token(token_hash)
            assert result is None
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_next_user_id_empty(self):
        store, db_path = self._make_store()
        try:
            assert store.next_user_id() == 1
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_next_user_id_after_insert(self):
        store, db_path = self._make_store()
        try:
            store.connection.execute(
                """
                INSERT INTO users (token_hash, token_prefix, user_id, role, pg_dbname, pg_user, pg_password)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("hash1", "malu_a_", 5, "executor", "db1", "u1", "p1"),
            )
            store.connection.commit()
            assert store.next_user_id() == 6
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_model_prompt_not_found(self):
        store, db_path = self._make_store()
        try:
            result = store.model_prompt("nonexistent-model")
            assert result is None
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_model_prompt_found(self):
        store, db_path = self._make_store()
        try:
            store.connection.execute(
                """
                INSERT INTO model_prompts
                    (model_name, model_identifier, api_format, system_prompt, base_url, max_tokens)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("gpt-4o", "gpt-4o-2024-05-13", "openai", "You are a helper.", "https://api.openai.com/v1", 4096),
            )
            store.connection.commit()

            result = store.model_prompt("gpt-4o")
            assert result is not None
            assert result["model_name"] == "gpt-4o"
            assert result["model_identifier"] == "gpt-4o-2024-05-13"
            assert result["api_format"] == "openai"
            assert result["max_tokens"] == 4096
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_init_db_seeds_default_prompts(self):
        store, db_path = self._make_store()
        try:
            rows = store.list_default_prompts()
            assert len(rows) > 0
            names = {(r["model_name"], r["task"]) for r in rows}
            assert ("gpt-4o", "extract") in names
            assert ("claude-sonnet", "skill_extract") in names
            assert ("text-embedding-3-small", "embed") in names
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_init_db_seed_is_idempotent(self):
        store, db_path = self._make_store()
        try:
            count_first = len(store.list_default_prompts())
            store.init_db()  # second run must not duplicate or overwrite
            assert len(store.list_default_prompts()) == count_first
        finally:
            Path(db_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_200(self):
        from app.main import app

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data == {"status": "ok"}
