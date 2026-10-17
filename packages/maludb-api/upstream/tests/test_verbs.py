"""
Tests for the verbs router — endpoint registration and validation.

Tests that don't need a live Postgres connection: verifying that endpoints
are registered (401 not 404 without auth) and testing input validation logic.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Endpoint registration — all verb endpoints should return 401, not 404,
# when called without an auth token.
# ---------------------------------------------------------------------------


class TestVerbEndpointsRegistered:
    """Verify every verb route is mounted (returns 401, not 404)."""

    def test_get_verbs(self):
        r = client.get("/v1/verbs")
        assert r.status_code == 401

    def test_post_verbs(self):
        r = client.post("/v1/verbs", json={"canonical_name": "test"})
        assert r.status_code == 401

    def test_get_verb_detail(self):
        r = client.get("/v1/verbs/1")
        assert r.status_code == 401

    def test_patch_verb(self):
        r = client.patch("/v1/verbs/1", json={"canonical_name": "updated"})
        assert r.status_code == 401

    def test_delete_verb(self):
        r = client.delete("/v1/verbs/1")
        assert r.status_code == 401

    def test_get_verb_subjects(self):
        r = client.get("/v1/verbs/1/subjects")
        assert r.status_code == 401


class TestVerbEndpointsNotFound:
    """Non-existent routes should still 404."""

    def test_nonexistent_verb_route(self):
        r = client.get("/v1/verbs/1/nonexistent")
        assert r.status_code == 404


class TestVerbAuthErrorShape:
    """Verify that 401 responses have the standard error shape."""

    def test_error_shape(self):
        r = client.get("/v1/verbs")
        assert r.status_code == 401
        data = r.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]
