"""
Tests for the attributes router — endpoint registration and validation.

Tests that don't need a live Postgres connection: verifying that endpoints
are registered (401 not 404 without auth), and that the standard error shape
is returned.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Endpoint registration — all attribute-related endpoints should return 401,
# not 404, when called without an auth token.
# ---------------------------------------------------------------------------

_AUTH_PATHS = [
    # Attributes
    ("GET", "/v1/attributes"),
    ("POST", "/v1/attributes"),
    ("GET", "/v1/attributes/1"),
    ("PATCH", "/v1/attributes/1"),
    ("DELETE", "/v1/attributes/1"),
    # Attribute Templates
    ("GET", "/v1/attribute-templates"),
    ("POST", "/v1/attribute-templates"),
    ("GET", "/v1/attribute-templates/1"),
    ("PATCH", "/v1/attribute-templates/1"),
    ("DELETE", "/v1/attribute-templates/1"),
    # Attribute Check
    ("GET", "/v1/attribute-check"),
]


class TestAttributesRouterRegistered:
    """Verify all attribute endpoints are mounted and return 401 (not 404) without auth."""

    @pytest.mark.parametrize("method,path", _AUTH_PATHS)
    def test_missing_auth_returns_401(self, method: str, path: str):
        response = client.request(method, path)
        assert response.status_code == 401, (
            f"{method} {path} returned {response.status_code}, expected 401"
        )
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "auth_missing"


class TestAttributesAuthErrorShape:
    """Verify that 401 responses have the standard error shape."""

    def test_error_shape(self):
        r = client.get("/v1/attributes")
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
            "/v1/attributes",
            headers={"Authorization": "Bearer bad_token_here"},
        )
        assert r.status_code == 401
        data = r.json()
        assert data["error"]["code"] == "auth_invalid"


class TestAttributeTemplatesAuthErrorShape:
    """Verify attribute-templates 401 responses have the standard error shape."""

    def test_error_shape(self):
        r = client.get("/v1/attribute-templates")
        assert r.status_code == 401
        data = r.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]
        assert data["error"]["code"] == "auth_missing"
        assert "Bearer" in data["error"]["message"]


class TestAttributeCheckAuthErrorShape:
    """Verify attribute-check 401 responses have the standard error shape."""

    def test_error_shape(self):
        r = client.get("/v1/attribute-check")
        assert r.status_code == 401
        data = r.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]
        assert data["error"]["code"] == "auth_missing"
        assert "Bearer" in data["error"]["message"]


class TestAttributesNotFound:
    """Non-existent routes should still 404."""

    def test_nonexistent_attribute_route(self):
        r = client.get("/v1/attributes/1/nonexistent")
        assert r.status_code == 404

    def test_nonexistent_template_route(self):
        r = client.get("/v1/attribute-templates/1/nonexistent")
        assert r.status_code == 404
