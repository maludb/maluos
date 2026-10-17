"""
Tests for the model_prompts router — endpoint registration.

Tests that don't need a live Postgres connection: verifying that endpoints
are registered and return appropriate errors without valid credentials.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Endpoint registration — model-prompts endpoints require Postgres login
# proof (not Bearer auth), so they should return 400 (missing_field) when
# called without credentials, not 404.
# ---------------------------------------------------------------------------

_PATHS = [
    ("GET", "/v1/model-prompts"),
    ("POST", "/v1/model-prompts"),
]


class TestModelPromptsRouterRegistered:
    """Verify model-prompts endpoints are mounted and respond (not 404)."""

    @pytest.mark.parametrize("method,path", _PATHS)
    def test_missing_creds_returns_400(self, method: str, path: str):
        response = client.request(method, path, content=b"{}", headers={"Content-Type": "application/json"})
        assert response.status_code == 400, (
            f"{method} {path} returned {response.status_code}, expected 400"
        )
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "missing_field"


class TestModelPromptsErrorShape:
    """Verify that error responses have the standard error shape."""

    def test_error_shape_post(self):
        r = client.post("/v1/model-prompts", json={})
        assert r.status_code == 400
        data = r.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]

    def test_error_shape_get(self):
        r = client.request("GET", "/v1/model-prompts", content=b"{}", headers={"Content-Type": "application/json"})
        assert r.status_code == 400
        data = r.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]


class TestModelPromptsNotFound:
    """Non-existent routes should still 404."""

    def test_nonexistent_route(self):
        r = client.get("/v1/model-prompts/nonexistent")
        assert r.status_code == 404
