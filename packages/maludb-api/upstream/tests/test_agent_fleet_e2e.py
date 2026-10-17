"""
End-to-end tests for the agent-fleet routes against a REAL tenant (maludb_core facades enabled).

Skipped unless MALUDB_E2E_TOKEN is set (same convention as test_rest_e2e.py):
    MALUDB_AUTH_STORE=/path/to/auth.db MALUDB_E2E_TOKEN=malu_… pytest tests/test_agent_fleet_e2e.py -v

Use a SCRATCH tenant: these tests write documents, chat sessions, profile entries and skills and
do not clean up (memory is append-only by doctrine). Every name carries a per-run suffix, so the
suite can be re-run against the same tenant.
"""

from __future__ import annotations

import base64
import os
import uuid

import pytest

TOKEN = os.environ.get("MALUDB_E2E_TOKEN")
pytestmark = pytest.mark.skipif(not TOKEN, reason="e2e disabled — set MALUDB_E2E_TOKEN (and MALUDB_AUTH_STORE)")
RUN = uuid.uuid4().hex[:8]


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        yield c


class TestRememberRecall:
    SUBJECT = f"Acme Widgets {RUN}"

    def test_remember_needs_no_model_and_recall_returns_the_text(self, client):
        text = f"{self.SUBJECT} pays invoices on the 15th by ACH, never by card."
        r = client.post(
            "/v1/memory/remember", json={"text": text, "subject": self.SUBJECT, "namespace": f"agent:{RUN}"}
        )
        assert r.status_code == 201, r.text
        assert r.json()["extractor"] == "none" and r.json()["namespace"] == f"agent:{RUN}"

        found = client.post(
            "/v1/memory/recall",
            json={"query": "how do they pay", "subject": self.SUBJECT, "namespaces": [f"agent:{RUN}", "org"]},
        ).json()
        assert [x["source_text"] for x in found["results"]] == [text]
        assert found["results"][0]["namespace"] == f"agent:{RUN}"

    def test_another_namespace_finds_nothing(self, client):
        found = client.post(
            "/v1/memory/recall",
            json={"query": "how do they pay", "subject": self.SUBJECT, "namespaces": [f"agent:other-{RUN}"]},
        ).json()
        assert found["results"] == []

    def test_free_text_proposes_the_subject_from_the_query(self, client):
        found = client.post(
            "/v1/memory/recall", json={"query": f"what do we know about {self.SUBJECT}", "namespaces": [f"agent:{RUN}"]}
        ).json()
        assert self.SUBJECT in found["subjects_tried"]
        assert len(found["results"]) == 1

    def test_a_query_naming_nothing_known_says_so(self, client):
        found = client.post(
            "/v1/memory/recall", json={"query": f"zzqx{RUN} qqzv{RUN}", "namespaces": [f"agent:{RUN}"]}
        ).json()
        assert found["results"] == [] and "compartmented" in found["note"]

    def test_remember_requires_a_subject(self, client):
        assert client.post("/v1/memory/remember", json={"text": "no subject"}).status_code == 400


class TestChat:
    def test_a_session_keeps_its_turns_in_order_and_is_searchable(self, client):
        marker = f"unpaid-{RUN}"
        s = client.post(
            "/v1/chat/sessions", json={"title": f"Run {RUN}", "principal": f"agent:{RUN}", "external_ref": f"run:{RUN}"}
        )
        assert s.status_code == 201, s.text
        sid = client.get(f"/v1/chat/sessions?external_ref=run:{RUN}").json()["sessions"][0]["id"]

        r = client.post(
            f"/v1/chat/sessions/{sid}/messages",
            json={
                "messages": [
                    {"role": "user", "text": "Reconcile Acme."},
                    {"role": "tool", "text": f"1 invoice {marker}", "tool_call_id": "call_1"},
                    {"role": "assistant", "text": "One invoice is outstanding."},
                ]
            },
        )
        assert r.status_code == 201 and r.json()["appended"] == 3

        transcript = client.get(f"/v1/chat/sessions/{sid}/messages").json()["messages"]
        assert [(m["ordinal"], m["role"]) for m in transcript] == [(1, "user"), (2, "tool"), (3, "assistant")]
        assert transcript[1]["tool_call_id"] == "call_1"

        hits = client.get(f"/v1/chat/search?q={marker}&principal=agent:{RUN}").json()["messages"]
        assert [(h["session_id"], h["ordinal"]) for h in hits] == [(sid, 2)]
        assert client.get(f"/v1/chat/search?q={marker}&principal=agent:someone-else").json()["messages"] == []

        assert client.post(f"/v1/chat/sessions/{sid}/finalize").status_code == 200

    def test_a_bad_message_lands_nothing(self, client):
        client.post("/v1/chat/sessions", json={"title": "atomic", "external_ref": f"atomic:{RUN}"})
        sid = client.get(f"/v1/chat/sessions?external_ref=atomic:{RUN}").json()["sessions"][0]["id"]
        r = client.post(
            f"/v1/chat/sessions/{sid}/messages",
            json={"messages": [{"role": "user", "text": "ok"}, {"role": "robot", "text": "no"}]},
        )
        assert r.status_code == 422
        assert client.get(f"/v1/chat/sessions/{sid}/messages").json()["messages"] == []

    def test_unknown_session(self, client):
        assert client.get("/v1/chat/sessions/999999999").status_code == 404


class TestProfile:
    REF = f"agent:{RUN}"

    def test_an_update_supersedes_and_history_survives(self, client):
        first = client.put(f"/v1/principals/{self.REF}/profile/naming", json={"value": "legal name"}).json()
        second = client.put(
            f"/v1/principals/{self.REF}/profile/naming", json={"value": "legal name, never the DBA"}
        ).json()
        assert first["supersedes"] is None and second["supersedes"] == first["id"]
        profile = client.get(f"/v1/principals/{self.REF}/profile").json()
        assert profile["entries"]["naming"]["value"] == "legal name, never the DBA"
        history = client.get(f"/v1/principals/{self.REF}/profile/naming/history").json()["history"]
        assert [h["value"] for h in history] == ["legal name, never the DBA", "legal name"]

    def test_structured_values_and_delete(self, client):
        client.put(f"/v1/principals/{self.REF}/profile/style", json={"value": {"lines": 3}})
        assert client.get(f"/v1/principals/{self.REF}/profile").json()["entries"]["style"]["value"] == {"lines": 3}
        assert client.delete(f"/v1/principals/{self.REF}/profile/style").status_code == 200
        assert "style" not in client.get(f"/v1/principals/{self.REF}/profile").json()["entries"]
        assert client.delete(f"/v1/principals/{self.REF}/profile/style").status_code == 404

    def test_profiles_do_not_mix_and_are_not_notes(self, client):
        assert client.get(f"/v1/principals/agent:nobody-{RUN}/profile").json()["entries"] == {}
        titles = [n["title"] for n in client.get("/v1/notes?type=note").json()["notes"]]
        assert not any(self.REF in t for t in titles)


class TestSkillsFleet:
    NAME = f"file-a-bill-{RUN}"

    def _ingest(self, client, version: str, reference: str):
        md = (
            f"---\nname: {self.NAME}\ndescription: How we file a vendor bill\nmetadata:\n  version: {version}\n---\n"
            "# Filing\nSee references/vendors.md.\n"
        )
        body = {
            "name": self.NAME,
            "description": "How we file a vendor bill",
            "markdown": md,
            "frontmatter": {
                "name": self.NAME,
                "description": "How we file a vendor bill",
                "metadata": {"version": version},
            },
            "files": [
                {"relative_path": "SKILL.md", "content_base64": base64.b64encode(md.encode()).decode()},
                {
                    "relative_path": "references/vendors.md",
                    "content_base64": base64.b64encode(reference.encode()).decode(),
                },
            ],
        }
        r = client.post("/v1/skills/ingest", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    def test_resolve_pins_and_one_file_can_be_read(self, client):
        self._ingest(client, "1.0.0", "# Vendors\nUse the legal name.\n")
        self._ingest(client, "1.1.0", "# Vendors\nUse the legal name. Never the DBA.\n")

        newest = client.get(f"/v1/skills/resolve?name={self.NAME}").json()
        pinned = client.get(f"/v1/skills/resolve?name={self.NAME}&version=1.0.0").json()
        assert newest["skill"]["version"] == "1.1.0" and newest["pinned_by"] is None
        assert pinned["skill"]["version"] == "1.0.0" and pinned["pinned_by"] == "version"
        by_hash = client.get(f"/v1/skills/resolve?name={self.NAME}&bundle_hash={pinned['skill']['bundle_hash']}").json()
        assert by_hash["skill"]["id"] == pinned["skill"]["id"]

        old = pinned["skill"]["id"]
        listing = client.get(f"/v1/skills/{old}/files").json()
        assert sorted(f["relative_path"] for f in listing["files"]) == ["SKILL.md", "references/vendors.md"]
        one = client.get(f"/v1/skills/{old}/files/references/vendors.md").json()["file"]
        assert one["text"] == "# Vendors\nUse the legal name.\n"
        assert client.get(f"/v1/skills/{old}/files/nope.md").status_code == 404

    def test_resolve_refusals(self, client):
        assert client.get(f"/v1/skills/resolve?name=nope-{RUN}").status_code == 404
        assert client.get("/v1/skills/resolve").status_code == 400
        assert client.get(f"/v1/skills/resolve?name={self.NAME}&version=1&bundle_hash=x").status_code == 422


class TestDeletedMemoryIsNotRecalled:
    """DELETE /v1/documents/{id} leaves the document's vector chunks in the engine (no tenant role
    can remove them). Recall must not return them."""

    SUBJECT = f"Forgotten Vendor {RUN}"
    NS = f"agent:forget-{RUN}"

    def _recall(self, client, limit=5):
        r = client.post(
            "/v1/memory/recall",
            json={"query": "payment terms", "subject": self.SUBJECT, "namespaces": [self.NS], "limit": limit},
        )
        assert r.status_code == 200, r.text
        return [x["source_text"] for x in r.json()["results"]]

    def test_a_deleted_memory_is_gone_from_recall_and_the_rest_still_fill_the_limit(self, client):
        texts = [f"{self.SUBJECT} fact {i}: net {30 + i} days." for i in range(4)]
        ids = []
        for text in texts:
            r = client.post("/v1/memory/remember", json={"text": text, "subject": self.SUBJECT, "namespace": self.NS})
            assert r.status_code == 201, r.text
            ids.append(r.json()["document_id"])
        assert sorted(self._recall(client)) == sorted(texts)

        for doc_id in ids[:2]:
            assert client.delete(f"/v1/documents/{doc_id}").status_code == 200

        assert sorted(self._recall(client)) == sorted(texts[2:])
        # limit=2 with two deleted hits ranked anywhere: the over-fetch must still return two.
        assert sorted(self._recall(client, limit=2)) == sorted(texts[2:])

        search = client.post(
            "/v1/memory/search", json={"query": "payment terms", "subject": self.SUBJECT, "namespace": self.NS}
        )
        assert search.status_code == 200, search.text
        assert sorted(x["source_text"] for x in search.json()["results"]) == sorted(texts[2:])
        assert [x["rank_no"] for x in search.json()["results"]] == [1, 2]
