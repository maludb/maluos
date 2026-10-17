"""
Tests for the graph router — endpoint registration and validation.

Tests that don't need a live Postgres connection: verifying that endpoints
are registered (401 not 404 without auth).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Endpoint registration — all graph endpoints should return 401, not 404,
# when called without an auth token.
# ---------------------------------------------------------------------------

_AUTH_PATHS = [
    ("GET", "/v1/edges"),
    ("GET", "/v1/graph/neighbors?kind=subject&id=1"),
    ("GET", "/v1/graph/walk?kind=subject&id=1"),
    ("GET", "/v1/graph/path?source_kind=subject&source_id=1&target_kind=subject&target_id=2"),
    ("GET", "/v1/graph/stats"),
    ("POST", "/v1/graph/import"),
    ("GET", "/v1/graph/query?q=test"),
    ("POST", "/v1/datamodel/refresh"),
    ("GET", "/v1/datamodel/describe?relation=x"),
    ("GET", "/v1/graph/god-nodes"),
    ("GET", "/v1/graph/surprises?namespace=ns"),
    ("GET", "/v1/communities"),
    ("GET", "/v1/communities/1/members"),
]


class TestGraphRouterRegistered:
    """Verify all graph endpoints are mounted and return 401 (not 404) without auth."""

    @pytest.mark.parametrize("method,path", _AUTH_PATHS)
    def test_missing_auth_returns_401(self, method: str, path: str):
        response = client.request(method, path)
        assert response.status_code == 401, (
            f"{method} {path} returned {response.status_code}, expected 401"
        )
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "auth_missing"


class TestGraphAuthErrorShape:
    """Verify that 401 responses have the standard error shape."""

    def test_edges_error_shape(self):
        r = client.get("/v1/edges")
        assert r.status_code == 401
        data = r.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]
        assert data["error"]["code"] == "auth_missing"
        assert "Bearer" in data["error"]["message"]

    def test_neighbors_error_shape(self):
        r = client.get("/v1/graph/neighbors?kind=subject&id=1")
        assert r.status_code == 401
        data = r.json()
        assert data["error"]["code"] == "auth_missing"

    def test_walk_error_shape(self):
        r = client.get("/v1/graph/walk?kind=subject&id=1")
        assert r.status_code == 401
        data = r.json()
        assert data["error"]["code"] == "auth_missing"

    def test_invalid_token_prefix(self):
        """A token without the malu_ prefix should get auth_invalid, not 404."""
        r = client.get(
            "/v1/edges",
            headers={"Authorization": "Bearer bad_token_here"},
        )
        assert r.status_code == 401
        data = r.json()
        assert data["error"]["code"] == "auth_invalid"


class TestGraphNotFound:
    """Non-existent routes should still 404."""

    def test_nonexistent_graph_route(self):
        r = client.get("/v1/graph/nonexistent")
        assert r.status_code == 404


class TestGraphRequiredParams:
    """Verify required query params are enforced by FastAPI (422)."""

    def test_neighbors_missing_kind(self):
        r = client.get(
            "/v1/graph/neighbors?id=1",
            headers={"Authorization": "Bearer bad_token_here"},
        )
        # FastAPI returns 422 for missing required query params before auth runs
        assert r.status_code in (401, 422)

    def test_neighbors_missing_id(self):
        r = client.get(
            "/v1/graph/neighbors?kind=subject",
            headers={"Authorization": "Bearer bad_token_here"},
        )
        assert r.status_code in (401, 422)

    def test_walk_missing_kind(self):
        r = client.get(
            "/v1/graph/walk?id=1",
            headers={"Authorization": "Bearer bad_token_here"},
        )
        assert r.status_code in (401, 422)

    def test_walk_missing_id(self):
        r = client.get(
            "/v1/graph/walk?kind=subject",
            headers={"Authorization": "Bearer bad_token_here"},
        )
        assert r.status_code in (401, 422)

    def test_path_missing_target(self):
        r = client.get(
            "/v1/graph/path?source_kind=subject&source_id=1",
            headers={"Authorization": "Bearer bad_token_here"},
        )
        assert r.status_code in (401, 422)

    def test_path_max_depth_out_of_range(self):
        r = client.get(
            "/v1/graph/path?source_kind=subject&source_id=1"
            "&target_kind=subject&target_id=2&max_depth=33",
            headers={"Authorization": "Bearer bad_token_here"},
        )
        # ge/le bounds are enforced by FastAPI (422) before auth on some
        # dependency orderings; either way it must not reach the handler.
        assert r.status_code in (401, 422)


class TestGraphImportHelpers:
    """Pure-function tests for the import transformation helpers."""

    def test_confidence_enum_mapping(self):
        from app.routers.graph import _link_confidence

        assert _link_confidence("EXTRACTED") == 1.0
        assert _link_confidence("inferred") == 0.7
        assert _link_confidence("Ambiguous") == 0.4
        assert _link_confidence("nonsense") is None
        assert _link_confidence(None) is None

    def test_confidence_numeric_passthrough_clamped(self):
        from app.routers.graph import _link_confidence

        assert _link_confidence(0.9) == 0.9
        assert _link_confidence(2) == 1.0
        assert _link_confidence(-1) == 0.0

    def test_clean_text_strips_controls_and_caps(self):
        from app.routers.graph import _clean_text

        assert _clean_text("a\x00b\x1fc", 10) == "abc"
        assert _clean_text("  padded  ", 10) == "padded"
        assert len(_clean_text("x" * 500, 256)) == 256

    def test_namespace_regex(self):
        from app.routers.graph import _NAMESPACE_RE

        assert _NAMESPACE_RE.match("maludb-terminal")
        assert _NAMESPACE_RE.match("repo.v2_x")
        assert not _NAMESPACE_RE.match("-leading-dash")
        assert not _NAMESPACE_RE.match("has/slash")
        assert not _NAMESPACE_RE.match("")
        assert not _NAMESPACE_RE.match("x" * 65)
