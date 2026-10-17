"""
Tests for the types router — endpoint registration and validation.

Tests that don't need a live Postgres connection: verifying that endpoints
are registered (401 not 404 without auth).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Endpoint registration — all type endpoints should return 401, not 404,
# when called without an auth token.
# ---------------------------------------------------------------------------


class TestSubjectTypesRegistered:
    def test_get_subject_types(self):
        r = client.get("/v1/subject-types")
        assert r.status_code == 401


class TestVerbTypesRegistered:
    def test_get_verb_types(self):
        r = client.get("/v1/verb-types")
        assert r.status_code == 401


class TestDocumentTypesRegistered:
    def test_get_document_types(self):
        r = client.get("/v1/document-types")
        assert r.status_code == 401

    def test_post_document_types(self):
        r = client.post("/v1/document-types", json={"document_type": "memo"})
        assert r.status_code == 401

    def test_patch_document_type(self):
        r = client.patch("/v1/document-types/1", json={"document_type": "updated"})
        assert r.status_code == 401

    def test_delete_document_type(self):
        r = client.delete("/v1/document-types/1")
        assert r.status_code == 401


class TestEpisodeTypesRegistered:
    def test_get_episode_types(self):
        r = client.get("/v1/episode-types")
        assert r.status_code == 401

    def test_post_episode_types(self):
        r = client.post("/v1/episode-types", json={"episode_type": "meeting"})
        assert r.status_code == 401

    def test_patch_episode_type(self):
        r = client.patch("/v1/episode-types/1", json={"episode_type": "updated"})
        assert r.status_code == 401

    def test_delete_episode_type(self):
        r = client.delete("/v1/episode-types/1")
        assert r.status_code == 401


class TestTypesNotFound:
    """Non-existent routes should still 404."""

    def test_nonexistent_subject_type_route(self):
        r = client.get("/v1/subject-types/1")
        assert r.status_code == 404

    def test_nonexistent_verb_type_route(self):
        r = client.get("/v1/verb-types/1")
        assert r.status_code == 404


class TestTypesAuthErrorShape:
    """Verify that 401 responses have the standard error shape."""

    def test_subject_types_error_shape(self):
        r = client.get("/v1/subject-types")
        assert r.status_code == 401
        data = r.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]

    def test_document_types_error_shape(self):
        r = client.get("/v1/document-types")
        assert r.status_code == 401
        data = r.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]

    def test_episode_types_error_shape(self):
        r = client.get("/v1/episode-types")
        assert r.status_code == 401
        data = r.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]
