"""
Tests for the skills router — endpoint registration and validation.

Tests that don't need a live Postgres connection: verifying that endpoints
are registered (401 not 404 without auth).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Endpoint registration — all skill endpoints should return 401, not 404,
# when called without an auth token.
# ---------------------------------------------------------------------------

_AUTH_PATHS = [
    ("GET", "/v1/skills"),
    ("POST", "/v1/skills"),
    ("GET", "/v1/skills/1"),
    ("GET", "/v1/skills/1/discovery"),
    ("PATCH", "/v1/skills/1"),
    ("DELETE", "/v1/skills/1"),
    ("POST", "/v1/skills/1/duplicate"),
    ("POST", "/v1/skills/ingest"),
    ("POST", "/v1/skills/reindex/run"),
    ("GET", "/v1/skills/1/bundle"),
]


class TestSkillsRouterRegistered:
    """Verify all skill endpoints are mounted and return 401 (not 404) without auth."""

    @pytest.mark.parametrize("method,path", _AUTH_PATHS)
    def test_missing_auth_returns_401(self, method: str, path: str):
        response = client.request(method, path)
        assert response.status_code == 401, f"{method} {path} returned {response.status_code}, expected 401"
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "auth_missing"


class TestSkillsAuthErrorShape:
    """Verify that 401 responses have the standard error shape."""

    def test_error_shape(self):
        r = client.get("/v1/skills")
        assert r.status_code == 401
        data = r.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]
        assert data["error"]["code"] == "auth_missing"
        assert "Bearer" in data["error"]["message"]

    def test_invalid_token_prefix(self):
        """A token without the malu_ prefix should get auth_invalid, not 404."""
        r = client.get(
            "/v1/skills",
            headers={"Authorization": "Bearer bad_token_here"},
        )
        assert r.status_code == 401
        data = r.json()
        assert data["error"]["code"] == "auth_invalid"


class TestSkillsNotFound:
    """Non-existent routes should still 404."""

    def test_nonexistent_skill_route(self):
        r = client.get("/v1/skills/1/nonexistent")
        assert r.status_code == 404
