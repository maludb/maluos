"""
End-to-end tests for principals, scopes and forgetting against a REAL tenant on maludb_core >= 0.106.0.

Skipped unless MALUDB_E2E_TOKEN is set (same convention as test_agent_fleet_e2e.py):
    MALUDB_AUTH_STORE=/path/to/auth.db MALUDB_E2E_TOKEN=malu_… pytest tests/test_scoping_e2e.py -v

Use a SCRATCH tenant. Every name carries a per-run suffix, so the suite can be re-run.
"""

from __future__ import annotations

import os
import uuid

import pytest

TOKEN = os.environ.get("MALUDB_E2E_TOKEN")
pytestmark = pytest.mark.skipif(not TOKEN, reason="e2e disabled — set MALUDB_E2E_TOKEN (and MALUDB_AUTH_STORE)")
RUN = uuid.uuid4().hex[:8]
SASHA, SEAMUS, OWNER = f"agent:s{RUN}", f"agent:m{RUN}", f"member:o{RUN}"
DEPT3, DEPT4 = f"dept:3-{RUN}", f"dept:4-{RUN}"
SUBJECT = f"Northwind {RUN}"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        if not c.get("/v1/whoami").json().get("engine_enforces_principals"):
            pytest.skip("tenant is not on maludb_core 0.106.0")
        yield c


def as_(ref: str, **extra) -> dict:
    return {"X-MaluDB-Principal": ref, **extra}


@pytest.fixture(scope="module")
def world(client):
    """Three principals, two departments, one remembered fact in each scope."""
    for ref, kind, home in ((SASHA, "agent", SASHA), (SEAMUS, "agent", SEAMUS), (OWNER, "human", OWNER)):
        assert client.put(f"/v1/principals/{ref}", json={"kind": kind, "home_scope": home}).status_code == 200
    assert client.put(f"/v1/principals/{SASHA}/scopes/{DEPT3}", json={"access_level": "read"}).status_code == 200
    assert client.put(f"/v1/principals/{OWNER}/scopes/{DEPT3}", json={"access_level": "write"}).status_code == 200
    assert client.put(f"/v1/principals/{SEAMUS}/scopes/{DEPT4}", json={"access_level": "write"}).status_code == 200
    docs = {}
    for scope, text in ((DEPT3, "pays Accounting by wire"), (DEPT4, "pays Sales a commission")):
        r = client.post(
            "/v1/memory/remember", json={"text": f"{SUBJECT} {text}.", "subject": SUBJECT, "namespace": scope}
        )
        assert r.status_code == 201, r.text
        docs[scope] = r.json()["document_id"]
    return docs


class TestWhoAmI:
    def test_the_tenant_is_unrestricted(self, client):
        assert client.get("/v1/whoami").json()["restricted"] is False

    def test_a_principal_sees_its_own_reach(self, client, world):
        me = client.get("/v1/whoami", headers=as_(SASHA)).json()
        assert me["restricted"] and me["principal_ref"] == SASHA
        assert sorted(me["read_scopes"]) == sorted([SASHA, DEPT3]) and me["write_scopes"] == [SASHA]

    def test_the_header_narrows_and_never_widens(self, client, world):
        narrowed = client.get("/v1/whoami", headers=as_(SASHA, **{"X-MaluDB-Scopes": f"{SASHA}, {DEPT4}"})).json()
        assert narrowed["read_scopes"] == [SASHA]

    def test_an_unknown_principal_has_nothing(self, client):
        me = client.get("/v1/whoami", headers=as_(f"agent:nobody{RUN}")).json()
        assert me["known"] is False and me["read_scopes"] == []

    def test_a_bad_header_is_refused(self, client):
        assert client.get("/v1/whoami", headers={"X-MaluDB-Principal": "not a ref"}).status_code == 400
        assert client.get("/v1/whoami", headers={"X-MaluDB-Scopes": "org"}).status_code == 400


class TestReadsAreScoped:
    def test_recall_in_a_held_scope_answers(self, client, world):
        found = client.post(
            "/v1/memory/recall",
            headers=as_(SASHA),
            json={"query": "how do they pay", "subject": SUBJECT, "namespaces": [DEPT3]},
        )
        assert found.status_code == 200, found.text
        assert [x["source_text"] for x in found.json()["results"]] == [f"{SUBJECT} pays Accounting by wire."]

    def test_recall_in_another_scope_is_refused_not_empty(self, client, world):
        r = client.post(
            "/v1/memory/recall",
            headers=as_(SASHA),
            json={"query": "how do they pay", "subject": SUBJECT, "namespaces": [DEPT4]},
        )
        assert r.status_code == 403, r.text

    def test_the_document_itself_is_as_private_as_its_chunk(self, client, world):
        assert client.get(f"/v1/documents/{world[DEPT3]}", headers=as_(SASHA)).status_code == 200
        assert client.get(f"/v1/documents/{world[DEPT4]}", headers=as_(SASHA)).status_code == 404


class TestWritesAreScoped:
    def test_read_access_is_not_write_access(self, client, world):
        r = client.post(
            "/v1/memory/remember",
            headers=as_(SASHA),
            json={"text": f"{SUBJECT} pays Sasha.", "subject": SUBJECT, "namespace": DEPT3},
        )
        assert r.status_code == 403, r.text

    def test_her_own_scope_is_hers(self, client, world):
        r = client.post(
            "/v1/memory/remember",
            headers=as_(SASHA),
            json={"text": f"{SUBJECT} pays late in August.", "subject": SUBJECT, "namespace": SASHA},
        )
        assert r.status_code == 201, r.text

    def test_readonly_refuses_even_that(self, client, world):
        r = client.post(
            "/v1/memory/remember",
            headers=as_(SASHA, **{"X-MaluDB-Readonly": "true"}),
            json={"text": f"{SUBJECT} pays nothing.", "subject": SUBJECT, "namespace": SASHA},
        )
        assert r.status_code == 403, r.text

    def test_a_principal_administers_nobody(self, client, world):
        r = client.put(f"/v1/principals/{SASHA}/scopes/{DEPT4}", headers=as_(SASHA), json={"access_level": "write"})
        assert r.status_code == 403, r.text

    def test_a_chat_session_can_be_started_in_a_scope(self, client, world):
        r = client.post("/v1/chat/sessions", json={"title": f"run transcript {RUN}", "scope": SASHA})
        assert r.status_code == 201, r.text
        sid = r.json()["session"]["chat_session"]["chat_session_id"]
        assert client.get(f"/v1/chat/sessions/{sid}", headers=as_(SASHA)).status_code == 200
        assert client.get(f"/v1/chat/sessions/{sid}", headers=as_(SEAMUS)).status_code == 404


class TestForgetting:
    def test_a_deleted_document_is_no_longer_recalled(self, client, world):
        text = f"{SUBJECT} pays a rebate nobody should remember."
        doc = client.post("/v1/memory/remember", json={"text": text, "subject": SUBJECT, "namespace": DEPT3}).json()[
            "document_id"
        ]
        ask = {"query": "rebate", "subject": SUBJECT, "namespaces": [DEPT3]}
        assert text in [x["source_text"] for x in client.post("/v1/memory/recall", json=ask).json()["results"]]

        gone = client.delete(f"/v1/documents/{doc}")
        assert gone.status_code == 200 and gone.json()["forgotten"]["chunks"] == 1, gone.text
        assert text not in [x["source_text"] for x in client.post("/v1/memory/recall", json=ask).json()["results"]]

    def test_a_principal_cannot_forget_what_it_can_only_read(self, client, world):
        assert client.delete(f"/v1/documents/{world[DEPT3]}", headers=as_(SASHA)).status_code == 403
