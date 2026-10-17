"""
Tests for the subjects router — validation paths only (no real Postgres DB).

We can verify:
  - Missing auth returns 401 (not 404), proving the router is registered.
  - Each endpoint group returns 401 without a Bearer token.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helper — all subject-related paths that require auth
# ---------------------------------------------------------------------------

_AUTH_PATHS = [
    ("GET", "/v1/subjects"),
    ("POST", "/v1/subjects"),
    ("GET", "/v1/subjects/1"),
    ("PATCH", "/v1/subjects/1"),
    ("DELETE", "/v1/subjects/1"),
    ("GET", "/v1/subjects/1/verbs"),
    ("POST", "/v1/subjects/1/verbs"),
    ("DELETE", "/v1/subjects/1/verbs/2"),
    ("GET", "/v1/subjects/1/related-subjects"),
    ("POST", "/v1/subjects/1/related-subjects"),
    ("DELETE", "/v1/subjects/1/related-subjects/2"),
    ("GET", "/v1/subject-relationships/1"),
    ("PATCH", "/v1/subject-relationships/1"),
    ("DELETE", "/v1/subject-relationships/1"),
]


class TestSubjectsRouterRegistered:
    """Verify all subject endpoints are mounted and return 401 (not 404) without auth."""

    @pytest.mark.parametrize("method,path", _AUTH_PATHS)
    def test_missing_auth_returns_401(self, method: str, path: str):
        response = client.request(method, path)
        assert response.status_code == 401, (
            f"{method} {path} returned {response.status_code}, expected 401"
        )
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "auth_missing"


class TestSubjectsRouterErrorShape:
    """Verify error responses have the standard JSON shape."""

    def test_error_shape(self):
        response = client.get("/v1/subjects")
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
            "/v1/subjects",
            headers={"Authorization": "Bearer bad_token_here"},
        )
        assert response.status_code == 401
        data = response.json()
        assert data["error"]["code"] == "auth_invalid"
