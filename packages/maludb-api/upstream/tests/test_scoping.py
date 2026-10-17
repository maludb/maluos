"""
Tests for the maludb_core 0.106.0 surface: the per-request principal (app/principal.py) and the
scoping router. No live Postgres: registration (401, not 404, without auth) and the pure helpers.
The SQL is exercised by tests/test_scoping_e2e.py against a real 0.106.0 tenant.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.errors import APIError
from app.main import app
from app.principal import REF, parse_scopes

client = TestClient(app, raise_server_exceptions=False)

_AUTH_PATHS = [
    ("GET", "/v1/whoami"),
    ("GET", "/v1/principals"),
    ("PUT", "/v1/principals/agent:44"),
    ("GET", "/v1/principals/agent:44/scopes"),
    ("PUT", "/v1/principals/agent:44/scopes/dept:3"),
    ("DELETE", "/v1/principals/agent:44/scopes/dept:3"),
    ("PUT", "/v1/scope"),
    ("DELETE", "/v1/memory/chunks/7"),
    ("POST", "/v1/skills/1/review"),
    ("PUT", "/v1/skills/1/principals/agent:44"),
    ("DELETE", "/v1/skills/1/principals/agent:44"),
    ("POST", "/v1/skills/1/loads"),
    ("GET", "/v1/skills/1/loads"),
    ("GET", "/v1/pools/1/presence"),
    ("POST", "/v1/pools/1/presence"),
    ("DELETE", "/v1/pools/1/presence"),
]


class TestRegistered:
    @pytest.mark.parametrize("method,path", _AUTH_PATHS)
    def test_missing_auth_returns_401(self, method: str, path: str):
        response = client.request(method, path)
        assert response.status_code == 401, f"{method} {path} returned {response.status_code}"
        assert response.json()["error"]["code"] == "auth_missing"

    def test_profile_routes_still_reach_their_own_handler(self):
        """PUT /v1/principals/{ref} must not swallow the MA profile routes under the same prefix."""
        assert client.get("/v1/principals/agent:44/profile").status_code == 401
        assert client.put("/v1/principals/agent:44/profile/style").status_code == 401


class TestScopesHeader:
    def test_absent_means_no_narrowing(self):
        assert parse_scopes(None) is None
        assert parse_scopes("   ") is None

    def test_comma_separated(self):
        assert parse_scopes("agent:44, dept:3 ,org") == ["agent:44", "dept:3", "org"]

    def test_json_array(self):
        assert parse_scopes('["agent:44", "dept:3"]') == ["agent:44", "dept:3"]

    def test_duplicates_and_blanks_dropped(self):
        assert parse_scopes("org,,org, dept:3") == ["org", "dept:3"]

    def test_an_empty_array_is_an_empty_list_not_absent(self):
        """[] narrows to NOTHING; it must not be read as 'no narrowing'."""
        assert parse_scopes("[]") == []

    @pytest.mark.parametrize("bad", ['["a", 1]', '{"a": 1}', "[oops", 'a"b'])
    def test_unreadable_is_refused_not_ignored(self, bad: str):
        with pytest.raises(APIError) as err:
            parse_scopes(bad)
        assert err.value.status == 400


class TestPrincipalRef:
    @pytest.mark.parametrize("ref", ["agent:44", "member:1", "svc.runner@office-1"])
    def test_accepts_the_hosts_names(self, ref: str):
        assert REF.match(ref)

    @pytest.mark.parametrize("ref", ["", " agent:44", "agent 44", "a" * 121, "agent:44;drop", "'x'"])
    def test_refuses_anything_else(self, ref: str):
        assert not REF.match(ref)


class TestIngestNamespaceReport:
    def test_applied_namespace_is_reported_plainly(self):
        from app.routers.memory import ingest_namespace_report

        assert ingest_namespace_report("agent:42", applied=True) == {"namespace": "agent:42"}

    def test_unapplied_namespace_still_says_so(self):
        from app.routers.memory import ingest_namespace_report

        report = ingest_namespace_report("agent:42")
        assert report["namespace"] == "default" and report["namespace_applied"] is False
