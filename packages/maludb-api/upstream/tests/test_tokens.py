"""
Tests for the tokens router — POST/GET/DELETE /v1/tokens.

Postgres credential verification is mocked (no live DB needed).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def _mock_auth_store(tmp_path: Path):
    """Point the auth store at a temporary SQLite database for each test."""
    from app.auth_store import AuthStore

    db_path = str(tmp_path / "test_auth.db")
    store = AuthStore(db_path)
    store.init_db()

    with patch("app.auth.get_auth_store", return_value=store), \
         patch("app.routers.tokens.get_auth_store", return_value=store):
        yield store


@pytest.fixture()
def client(_mock_auth_store) -> TestClient:
    """TestClient with mocked auth store."""
    from app.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /v1/tokens — validation
# ---------------------------------------------------------------------------


class TestCreateTokenValidation:
    def test_missing_pg_dbname(self, client: TestClient):
        resp = client.post("/v1/tokens", json={"pg_user": "u", "pg_password": "p"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "missing_field"

    def test_missing_pg_user(self, client: TestClient):
        resp = client.post("/v1/tokens", json={"pg_dbname": "db", "pg_password": "p"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "missing_field"

    def test_missing_pg_password(self, client: TestClient):
        resp = client.post("/v1/tokens", json={"pg_dbname": "db", "pg_user": "u"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "missing_field"

    def test_empty_pg_dbname(self, client: TestClient):
        resp = client.post("/v1/tokens", json={"pg_dbname": "  ", "pg_user": "u", "pg_password": "p"})
        assert resp.status_code == 400

    def test_invalid_expires_in_days_string(self, client: TestClient):
        with patch("app.routers.tokens.test_credentials", return_value=True):
            resp = client.post(
                "/v1/tokens",
                json={"pg_dbname": "db", "pg_user": "u", "pg_password": "p", "expires_in_days": "seven"},
            )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_failed"

    def test_invalid_expires_in_days_negative(self, client: TestClient):
        with patch("app.routers.tokens.test_credentials", return_value=True):
            resp = client.post(
                "/v1/tokens",
                json={"pg_dbname": "db", "pg_user": "u", "pg_password": "p", "expires_in_days": -5},
            )
        assert resp.status_code == 422

    def test_invalid_expires_in_days_zero(self, client: TestClient):
        with patch("app.routers.tokens.test_credentials", return_value=True):
            resp = client.post(
                "/v1/tokens",
                json={"pg_dbname": "db", "pg_user": "u", "pg_password": "p", "expires_in_days": 0},
            )
        assert resp.status_code == 422

    def test_pg_auth_failed(self, client: TestClient):
        with patch("app.routers.tokens.test_credentials", return_value=False):
            resp = client.post(
                "/v1/tokens",
                json={"pg_dbname": "db", "pg_user": "u", "pg_password": "wrong"},
            )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "pg_auth_failed"


# ---------------------------------------------------------------------------
# POST /v1/tokens — success paths
# ---------------------------------------------------------------------------


class TestCreateTokenSuccess:
    def test_creates_token_with_defaults(self, client: TestClient):
        with patch("app.routers.tokens.test_credentials", return_value=True):
            resp = client.post(
                "/v1/tokens",
                json={"pg_dbname": "mydb", "pg_user": "myuser", "pg_password": "mypass"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["token"].startswith("malu_")
        assert data["role"] == "executor"
        assert data["pg_dbname"] == "mydb"
        assert data["pg_user"] == "myuser"
        assert data["user_id"] == 1  # first auto-assigned
        assert data["expires_at"] is None
        assert data["device_name"] is None
        assert isinstance(data["id"], int)

    def test_creates_token_with_all_options(self, client: TestClient):
        with patch("app.routers.tokens.test_credentials", return_value=True):
            resp = client.post(
                "/v1/tokens",
                json={
                    "pg_dbname": "mydb",
                    "pg_user": "myuser",
                    "pg_password": "mypass",
                    "role": "viewer",
                    "user_id": 42,
                    "device_name": "laptop",
                    "expires_in_days": 30,
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["role"] == "viewer"
        assert data["user_id"] == 42
        assert data["device_name"] == "laptop"
        assert data["expires_at"] is not None

    def test_token_hash_is_stored_correctly(self, client: TestClient, _mock_auth_store):
        """Verify that the stored hash matches sha256(token body after malu_)."""
        with patch("app.routers.tokens.test_credentials", return_value=True):
            resp = client.post(
                "/v1/tokens",
                json={"pg_dbname": "mydb", "pg_user": "myuser", "pg_password": "mypass"},
            )
        data = resp.json()
        token_body = data["token"][len("malu_"):]
        expected_hash = hashlib.sha256(token_body.encode()).hexdigest()

        # Look up the hash in the store
        row = _mock_auth_store.resolve_token(expected_hash)
        assert row is not None
        assert row["pg_dbname"] == "mydb"
        assert row["pg_user"] == "myuser"


# ---------------------------------------------------------------------------
# GET /v1/tokens — validation
# ---------------------------------------------------------------------------


class TestListTokensValidation:
    def test_missing_fields(self, client: TestClient):
        resp = client.request("GET", "/v1/tokens", json={"pg_dbname": "db"})
        assert resp.status_code == 400

    def test_pg_auth_failed(self, client: TestClient):
        with patch("app.routers.tokens.test_credentials", return_value=False):
            resp = client.request(
                "GET",
                "/v1/tokens",
                json={"pg_dbname": "db", "pg_user": "u", "pg_password": "wrong"},
            )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /v1/tokens — success paths
# ---------------------------------------------------------------------------


class TestListTokensSuccess:
    def test_list_empty(self, client: TestClient):
        with patch("app.routers.tokens.test_credentials", return_value=True):
            resp = client.request(
                "GET",
                "/v1/tokens",
                json={"pg_dbname": "db", "pg_user": "u", "pg_password": "p"},
            )
        assert resp.status_code == 200
        assert resp.json()["tokens"] == []

    def test_list_returns_created_tokens(self, client: TestClient):
        with patch("app.routers.tokens.test_credentials", return_value=True):
            # Create two tokens
            client.post("/v1/tokens", json={"pg_dbname": "db", "pg_user": "u", "pg_password": "p"})
            client.post("/v1/tokens", json={"pg_dbname": "db", "pg_user": "u", "pg_password": "p"})

            resp = client.request(
                "GET",
                "/v1/tokens",
                json={"pg_dbname": "db", "pg_user": "u", "pg_password": "p"},
            )
        assert resp.status_code == 200
        tokens = resp.json()["tokens"]
        assert len(tokens) == 2
        # Should not contain token_hash or pg_password
        for t in tokens:
            assert "token_hash" not in t
            assert "pg_password" not in t
            assert "token_prefix" in t
            assert "id" in t
            assert isinstance(t["id"], int)
            assert isinstance(t["user_id"], int)


# ---------------------------------------------------------------------------
# DELETE /v1/tokens/{id} — validation
# ---------------------------------------------------------------------------


class TestDeleteTokenValidation:
    def test_missing_fields(self, client: TestClient):
        resp = client.request("DELETE", "/v1/tokens/1", json={"pg_dbname": "db"})
        assert resp.status_code == 400

    def test_pg_auth_failed(self, client: TestClient):
        with patch("app.routers.tokens.test_credentials", return_value=False):
            resp = client.request(
                "DELETE",
                "/v1/tokens/1",
                json={"pg_dbname": "db", "pg_user": "u", "pg_password": "wrong"},
            )
        assert resp.status_code == 403

    def test_not_found(self, client: TestClient):
        with patch("app.routers.tokens.test_credentials", return_value=True):
            resp = client.request(
                "DELETE",
                "/v1/tokens/9999",
                json={"pg_dbname": "db", "pg_user": "u", "pg_password": "p"},
            )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# DELETE /v1/tokens/{id} — success + ownership check
# ---------------------------------------------------------------------------


class TestDeleteTokenSuccess:
    def test_delete_own_token(self, client: TestClient):
        with patch("app.routers.tokens.test_credentials", return_value=True):
            create_resp = client.post(
                "/v1/tokens",
                json={"pg_dbname": "db", "pg_user": "u", "pg_password": "p"},
            )
            token_id = create_resp.json()["id"]

            resp = client.request(
                "DELETE",
                f"/v1/tokens/{token_id}",
                json={"pg_dbname": "db", "pg_user": "u", "pg_password": "p"},
            )
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert resp.json()["id"] == token_id

    def test_cannot_delete_other_users_token(self, client: TestClient):
        with patch("app.routers.tokens.test_credentials", return_value=True):
            # Create a token for user_a
            create_resp = client.post(
                "/v1/tokens",
                json={"pg_dbname": "db_a", "pg_user": "user_a", "pg_password": "pass_a"},
            )
            token_id = create_resp.json()["id"]

            # Try to delete it with user_b's credentials
            resp = client.request(
                "DELETE",
                f"/v1/tokens/{token_id}",
                json={"pg_dbname": "db_b", "pg_user": "user_b", "pg_password": "pass_b"},
            )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "forbidden"


# ---------------------------------------------------------------------------
# Expiry — resolve_token() compares instants, not strings
# ---------------------------------------------------------------------------


class TestTokenExpiry:
    """tokens.py stores "YYYY-MM-DD HH:MM:SS"; resolve_token() used to compare that string with an
    ISO "…T…Z" now. On the token's last day the space sorted below the "T" and the token was
    already dead — fatal for a token that lives minutes rather than days."""

    @staticmethod
    def _insert(store, token_hash: str, expires_at: str | None) -> None:
        store.connection.execute(
            """
            INSERT INTO users (token_hash, token_prefix, user_id, role, pg_dbname, pg_user, pg_password, expires_at)
            VALUES (?, 'testpfx1', 1, 'user', 'db', 'u', 'p', ?)
            """,
            (token_hash, expires_at),
        )
        store.connection.commit()

    def test_token_expiring_later_today_still_resolves(self, _mock_auth_store):
        from datetime import UTC, datetime, timedelta

        soon = (datetime.now(UTC) + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        self._insert(_mock_auth_store, "hash-soon", soon)
        assert _mock_auth_store.resolve_token("hash-soon") is not None

    def test_expired_token_does_not_resolve(self, _mock_auth_store):
        from datetime import UTC, datetime, timedelta

        past = (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        self._insert(_mock_auth_store, "hash-past", past)
        assert _mock_auth_store.resolve_token("hash-past") is None

    def test_iso_spelling_is_read_too(self, _mock_auth_store):
        from datetime import UTC, datetime, timedelta

        soon = (datetime.now(UTC) + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._insert(_mock_auth_store, "hash-iso", soon)
        assert _mock_auth_store.resolve_token("hash-iso") is not None

    def test_no_expiry_resolves(self, _mock_auth_store):
        self._insert(_mock_auth_store, "hash-never", None)
        assert _mock_auth_store.resolve_token("hash-never") is not None
