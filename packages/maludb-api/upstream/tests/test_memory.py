"""
Tests for the memory router — endpoint registration.

Tests that don't need a live Postgres connection: verifying that endpoints
are registered (401 not 404 without auth).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Endpoint registration — all memory endpoints should return 401, not 404,
# when called without an auth token.
# ---------------------------------------------------------------------------

_AUTH_PATHS = [
    ("GET", "/v1/memory/config"),
    ("POST", "/v1/memory/config"),
    ("PUT", "/v1/memory/config"),
    ("POST", "/v1/memory/documents"),
    ("POST", "/v1/memory/search"),
    ("POST", "/v1/memory/ingest"),
    ("POST", "/v1/memory/reindex/run"),
    ("POST", "/v1/memory/embeddings/run"),
]


class TestMemoryRouterRegistered:
    """Verify all memory endpoints are mounted and return 401 (not 404) without auth."""

    @pytest.mark.parametrize("method,path", _AUTH_PATHS)
    def test_missing_auth_returns_401(self, method: str, path: str):
        response = client.request(method, path)
        assert response.status_code == 401, f"{method} {path} returned {response.status_code}, expected 401"
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "auth_missing"


class TestMemoryAuthErrorShape:
    """Verify that 401 responses have the standard error shape."""

    def test_error_shape(self):
        r = client.get("/v1/memory/config")
        assert r.status_code == 401
        data = r.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]
        assert data["error"]["code"] == "auth_missing"
        assert "Bearer" in data["error"]["message"]


class TestMemoryNotFound:
    """Non-existent routes should still 404."""

    def test_nonexistent_memory_route(self):
        r = client.get("/v1/memory/nonexistent")
        assert r.status_code in (404, 405)


class TestIngestNamespaceReport:
    """/v1/memory/ingest cannot store into a namespace; it must not claim it did."""

    def test_default_namespace_is_reported_plainly(self):
        from app.routers.memory import ingest_namespace_report

        assert ingest_namespace_report("default") == {"namespace": "default"}

    def test_a_requested_namespace_is_reported_as_not_applied(self):
        from app.routers.memory import ingest_namespace_report

        report = ingest_namespace_report("agent:42")
        assert report["namespace"] == "default"
        assert report["namespace_requested"] == "agent:42"
        assert report["namespace_applied"] is False
        assert "agent:42" in report["warnings"][0]
