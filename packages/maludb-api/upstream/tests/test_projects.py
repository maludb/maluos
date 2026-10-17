"""
Tests for the projects router — endpoint registration and validation.

Tests that don't need a live Postgres connection: verifying that endpoints
are registered (401 not 404 without auth) and testing input validation logic.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helper — all project-related paths that require auth
# ---------------------------------------------------------------------------

_AUTH_PATHS = [
    ("GET", "/v1/projects"),
    ("POST", "/v1/projects"),
    ("GET", "/v1/projects/1"),
    ("PATCH", "/v1/projects/1"),
    ("DELETE", "/v1/projects/1"),
    ("POST", "/v1/projects/1/archive"),
    ("POST", "/v1/projects/1/unarchive"),
    ("POST", "/v1/projects/1/subjects"),
    ("PUT", "/v1/projects/1/subjects"),
    ("DELETE", "/v1/projects/1/subjects/2"),
    ("POST", "/v1/projects/1/verbs"),
    ("PUT", "/v1/projects/1/verbs"),
    ("DELETE", "/v1/projects/1/verbs/2"),
]


class TestProjectsRouterRegistered:
    """Verify all project endpoints are mounted and return 401 (not 404) without auth."""

    @pytest.mark.parametrize("method,path", _AUTH_PATHS)
    def test_missing_auth_returns_401(self, method: str, path: str):
        response = client.request(method, path)
        assert response.status_code == 401, (
            f"{method} {path} returned {response.status_code}, expected 401"
        )
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "auth_missing"


class TestProjectsRouterErrorShape:
    """Verify error responses have the standard JSON shape."""

    def test_error_shape(self):
        response = client.get("/v1/projects")
        assert response.status_code == 401
        data = response.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]
        assert data["error"]["code"] == "auth_missing"
        assert "Bearer" in data["error"]["message"]

    def test_invalid_token_prefix(self):
        """A token without the malu_ prefix should get auth_invalid, not 404."""
        response = client.get(
            "/v1/projects",
            headers={"Authorization": "Bearer bad_token_here"},
        )
        assert response.status_code == 401
        data = response.json()
        assert data["error"]["code"] == "auth_invalid"


class TestProjectsNotFound:
    """Non-existent routes should still 404."""

    def test_nonexistent_project_route(self):
        r = client.get("/v1/projects/1/nonexistent")
        assert r.status_code == 404
