"""
Tests for the agent-fleet routes: agent_memory (remember / recall), chat, principals, skills_fleet.

No live Postgres needed: endpoint registration (401, not 404, without auth) and the pure helpers.
The SQL itself is exercised by tests/test_agent_fleet_e2e.py against a real tenant.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.errors import APIError
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

_AUTH_PATHS = [
    ("POST", "/v1/memory/remember"),
    ("POST", "/v1/memory/recall"),
    ("POST", "/v1/chat/sessions"),
    ("GET", "/v1/chat/sessions"),
    ("GET", "/v1/chat/search?q=hello"),
    ("GET", "/v1/chat/sessions/1"),
    ("POST", "/v1/chat/sessions/1/messages"),
    ("GET", "/v1/chat/sessions/1/messages"),
    ("POST", "/v1/chat/sessions/1/finalize"),
    ("GET", "/v1/principals/agent:44/profile"),
    ("PUT", "/v1/principals/agent:44/profile/style"),
    ("DELETE", "/v1/principals/agent:44/profile/style"),
    ("GET", "/v1/principals/agent:44/profile/style/history"),
    ("GET", "/v1/skills/resolve?name=x"),
    ("GET", "/v1/skills/1/files"),
    ("GET", "/v1/skills/1/files/references/a.md"),
]


class TestRegistered:
    @pytest.mark.parametrize("method,path", _AUTH_PATHS)
    def test_missing_auth_returns_401(self, method: str, path: str):
        response = client.request(method, path)
        assert response.status_code == 401, f"{method} {path} returned {response.status_code}"
        assert response.json()["error"]["code"] == "auth_missing"

    def test_resolve_is_not_swallowed_by_the_skill_id_route(self):
        """/v1/skills/resolve must reach its own handler: mounted after skills.py it would hit
        /v1/skills/{skill_id:int} and answer 422 before auth was even considered."""
        assert client.get("/v1/skills/resolve?name=x").status_code == 401

    def test_existing_skill_routes_still_answer(self):
        assert client.get("/v1/skills/1").status_code == 401
        assert client.get("/v1/skills/1/bundle").status_code == 401


class TestRememberEdges:
    def test_the_text_itself_is_the_span(self):
        from app.routers.agent_memory import build_remember_edges

        edges = build_remember_edges("Acme pays on the 15th.", ["Acme"], "noted", None, 2000, 200)
        assert edges == [
            {
                "subject_text": "Acme",
                "verb_text": "noted",
                "source_span": "Acme pays on the 15th.",
                "provenance": "provided",
            }
        ]

    def test_one_edge_per_subject_and_chunk(self):
        from app.routers.agent_memory import build_remember_edges

        text = ("First paragraph about closing the books. " * 12) + "\n\n" + ("Second paragraph about the CFO. " * 12)
        edges = build_remember_edges(text, ["month-end close", "Accounting"], "noted", "process", 300, 0)
        chunks = {e["source_span"] for e in edges}
        assert len(chunks) > 1
        assert len(edges) == 2 * len(chunks)
        assert all(e["subject_type"] == "process" for e in edges)
        assert all(len(e["source_span"]) <= 300 for e in edges)


class TestMergeRecall:
    def test_best_first_across_namespaces_and_no_duplicates(self):
        from app.routers.agent_memory import merge_recall

        merged = merge_recall(
            [
                (
                    "agent:44",
                    [
                        {"chunk_id": 1, "similarity": 0.4, "source_text": "a"},
                        {"chunk_id": 1, "similarity": 0.4, "source_text": "a"},
                    ],
                ),
                (
                    "dept:3",
                    [
                        {"chunk_id": 1, "similarity": 0.9, "source_text": "b"},
                        {"chunk_id": 7, "similarity": None, "source_text": "c"},
                    ],
                ),
            ],
            limit=5,
        )
        assert [(r["namespace"], r["chunk_id"], r["rank_no"]) for r in merged] == [
            ("dept:3", 1, 1),
            ("agent:44", 1, 2),
            ("dept:3", 7, 3),
        ]

    def test_limit(self):
        from app.routers.agent_memory import merge_recall

        rows = [{"chunk_id": i, "similarity": i / 10} for i in range(1, 8)]
        assert [r["chunk_id"] for r in merge_recall([("n", rows)], limit=3)] == [7, 6, 5]


class TestChatMessages:
    def test_a_known_role_and_text(self):
        from app.routers.chat import normalise_message

        m = normalise_message({"role": "tool", "text": "3 rows", "tool_call_id": "call_1", "metadata": {"ms": 12}}, 0)
        assert (m["role"], m["text"], m["content"]) == ("tool", "3 rows", None)
        assert json.loads(m["metadata"]) == {"ms": 12, "tool_call_id": "call_1"}

    def test_structured_content_alone_is_enough(self):
        from app.routers.chat import normalise_message

        m = normalise_message({"role": "assistant", "content": {"tool_calls": [{"name": "find"}]}}, 0)
        assert m["text"] is None and json.loads(m["content"]) == {"tool_calls": [{"name": "find"}]}

    @pytest.mark.parametrize(
        "bad", [{"role": "robot", "text": "x"}, {"role": "user"}, {"role": "user", "text": ""}, "nope"]
    )
    def test_refusals(self, bad):
        from app.routers.chat import normalise_message

        with pytest.raises(APIError):
            normalise_message(bad, 3)


class TestPrincipalNames:
    @pytest.mark.parametrize("ref", ["agent:44", "member:1", "dept.accounting", "a@b"])
    def test_good_refs(self, ref):
        from app.routers.principals import check_ref

        assert check_ref(ref) == ref

    @pytest.mark.parametrize("ref", ["", " agent", "agent 44", "a/b", "x" * 121, "'; drop"])
    def test_bad_refs(self, ref):
        from app.routers.principals import check_ref

        with pytest.raises(APIError):
            check_ref(ref)

    @pytest.mark.parametrize("key", ["bad key", "k/v", "", "x" * 81])
    def test_bad_keys(self, key):
        from app.routers.principals import check_key

        with pytest.raises(APIError):
            check_key(key)


class TestDeletedDocumentsAreNotRecalled:
    """A deleted document's vector chunks outlive it in the engine; search must not return them."""

    @staticmethod
    def _hit(chunk_id, document_id, rank):
        return {"chunk_id": chunk_id, "document_id": document_id, "rank_no": rank, "source_text": f"c{chunk_id}"}

    def test_a_hit_whose_document_is_gone_is_dropped_and_ranks_stay_contiguous(self):
        from app.routers.memory import drop_deleted_documents

        rows = [self._hit(1, 10, 1), self._hit(2, 11, 2), self._hit(3, 12, 3)]
        kept = drop_deleted_documents(rows, live_documents={10, 12}, limit=5)
        assert [(r["chunk_id"], r["rank_no"]) for r in kept] == [(1, 1), (3, 2)]

    def test_a_statement_only_chunk_names_no_document_and_is_kept(self):
        from app.routers.memory import drop_deleted_documents

        kept = drop_deleted_documents([self._hit(1, None, 1)], live_documents=set(), limit=5)
        assert [r["chunk_id"] for r in kept] == [1]

    def test_the_over_fetch_refills_the_limit(self):
        from app.routers.memory import drop_deleted_documents

        rows = [self._hit(i, 100 + i, i) for i in range(1, 7)]
        kept = drop_deleted_documents(rows, live_documents={103, 104, 105, 106}, limit=2)
        assert [r["chunk_id"] for r in kept] == [3, 4]

    def test_nothing_live_means_nothing_returned(self):
        from app.routers.memory import drop_deleted_documents

        assert drop_deleted_documents([self._hit(1, 10, 1)], live_documents=set(), limit=5) == []
