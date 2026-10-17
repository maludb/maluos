"""
Tests for POST /v1/memory/answer (M1): registration, the pure verification, and the answer flow with the
retrieval and the model faked — no Postgres, no provider. The SQL and the live model are exercised against a
scratch tenant by the proof in docs/memory-answer.md.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.errors import APIError
from app.main import app
from app.routers.memory_answer import (
    answer_core,
    build_messages,
    norm,
    parse_request,
    quoted_spans,
    verify,
)

client = TestClient(app, raise_server_exceptions=False)

EVIDENCE = [
    {
        "n": 1,
        "chunk_id": 11,
        "document_id": 5,
        "statement_id": 1,
        "similarity": 0.8,
        "subject": "Warranty",
        "verb": "covers",
        "text": "The battery is covered for 24 months from the date of purchase.  Exceptions— misuse voids it.",
        "document": {"title": "Terms 4.2", "metadata": {"section_id": 7}},
    },
    {
        "n": 2,
        "chunk_id": 12,
        "document_id": 6,
        "statement_id": 2,
        "similarity": 0.6,
        "subject": "Warranty",
        "verb": "excludes",
        "text": "Water damage is not covered.",
        "document": {"title": "Terms 4.3", "metadata": {}},
    },
]
REQ = {
    "question": "How long is the battery covered?",
    "facts": "",
    "system": "Be brief.",
    "history": [],
    "max_evidence": 12,
    "min_similarity": 0.2,
    "namespace": "kb:1",
    "project": None,
    "model": None,
    "embedding_model": None,
}
CFG = {"model_identifier": "fake-model", "api_format": "openai", "token": "x", "base_url": "http://x"}


def retrieve_of(evidence, note=None):
    return lambda auth, req: {
        "evidence": evidence,
        "subjects_tried": ["Warranty"],
        "embedding_model": "e",
        "note": note,
    }


class Completer:
    """A fake model: answers with each queued parse in turn and counts its calls."""

    def __init__(self, *parsed):
        self.queue, self.calls = list(parsed), []

    def __call__(self, cfg, system, user):
        self.calls.append((system, user))
        return self.queue.pop(0), {"input_tokens": 100, "output_tokens": 20}


def run(evidence, completer, req=None):
    return answer_core(
        None, {**REQ, **(req or {})}, retrieve=retrieve_of(evidence), resolve=lambda a, n, m: CFG, complete=completer
    )


GOOD = {
    "sufficient": True,
    "answer_md": "It is covered for 24 months [1].",
    "citations": [{"n": 1, "quote": "covered for 24 months from the date of purchase"}],
}


def test_the_route_is_registered():
    r = client.post("/v1/memory/answer", json={"question": "x"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "auth_missing"


class TestNorm:
    def test_whitespace_quotes_dashes_and_case_are_ignored(self):
        assert norm("  The “Battery” —\n is  ") == norm('the "battery" - is')

    def test_quoted_spans_find_straight_curly_and_blockquote(self):
        md = (
            'He said "the battery is covered for 24 months" and \u201cwater damage is not covered\u201d.\n'
            "> Exceptions\u2014 misuse voids it.\n"
            '"short"'
        )
        spans = quoted_spans(md)
        assert len(spans) == 3 and "short" not in spans


class TestVerify:
    def test_an_exact_quote_modulo_whitespace_and_case_passes(self):
        v = verify(
            {
                "sufficient": True,
                "answer_md": "x",
                "citations": [{"n": 1, "quote": "Covered for 24 MONTHS from\nthe date"}],
            },
            EVIDENCE,
        )
        assert len(v["citations"]) == 1 and not v["bad_citations"]

    def test_a_quote_that_is_not_in_the_cited_item_fails_even_if_another_item_has_it(self):
        v = verify({"citations": [{"n": 2, "quote": "covered for 24 months"}]}, EVIDENCE)
        assert v["bad_citations"] and not v["citations"]

    def test_unknown_evidence_numbers_and_tiny_quotes_fail(self):
        v = verify(
            {
                "citations": [
                    {"n": 9, "quote": "water damage"},
                    {"n": 2, "quote": "wa"},
                    {"n": "x", "quote": "water damage"},
                    "junk",
                ]
            },
            EVIDENCE,
        )
        assert len(v["bad_citations"]) == 3 and not v["citations"]

    def test_a_quoted_span_in_the_answer_must_be_in_the_evidence(self):
        ok = verify({"answer_md": 'It says "water damage is not covered".', "citations": []}, EVIDENCE)
        bad = verify({"answer_md": 'It says "water damage is covered for ten years".', "citations": []}, EVIDENCE)
        assert not ok["bad_spans"] and bad["bad_spans"]

    def test_only_a_literal_true_is_sufficient(self):
        assert verify({"sufficient": "true"}, EVIDENCE)["sufficient"] is False


class TestFlow:
    def test_no_evidence_never_calls_a_model(self):
        c = Completer()
        out = answer_core(
            None, REQ, retrieve=retrieve_of([], "none"), resolve=lambda *a: pytest.fail("resolved a model"), complete=c
        )
        assert (
            out["status"] == "no_evidence" and out["answer_md"] is None and c.calls == [] and out["usage"]["calls"] == 0
        )
        assert out["note"] == "none"

    def test_an_answer_with_verified_citations(self):
        c = Completer(GOOD)
        out = run(EVIDENCE, c)
        assert out["status"] == "answered" and out["answer_md"].startswith("It is covered")
        assert out["citations"] == [
            {
                "n": 1,
                "quote": "covered for 24 months from the date of purchase",
                "chunk_id": 11,
                "document_id": 5,
                "verified": True,
            }
        ]
        assert out["confidence"] == 0.8 and out["usage"] == {"input_tokens": 100, "output_tokens": 20, "calls": 1}
        assert out["model"] == "fake-model" and len(out["evidence"]) == 2

    def test_one_repair_attempt_names_the_failures(self):
        bad = {"sufficient": True, "answer_md": "x [1]", "citations": [{"n": 1, "quote": "covered for 36 months"}]}
        c = Completer(bad, GOOD)
        out = run(EVIDENCE, c)
        assert out["status"] == "answered" and out["usage"]["calls"] == 2 and out["usage"]["input_tokens"] == 200
        assert (
            "covered for 36 months" in c.calls[1][1] and "REJECTED" in c.calls[1][1] and "REJECTED" not in c.calls[0][1]
        )

    def test_a_quote_that_stays_unverified_withholds_the_answer(self):
        bad = {"sufficient": True, "answer_md": "x [1]", "citations": [{"n": 1, "quote": "covered for 36 months"}]}
        out = run(EVIDENCE, Completer(bad, bad))
        assert out["status"] == "unverified" and out["answer_md"] is None and out["citations"] == []
        assert out["unverified_quotes"] == ["covered for 36 months"] and out["usage"]["calls"] == 2 and out["evidence"]

    def test_a_fabricated_quote_inside_the_answer_text_is_caught(self):
        bad = {
            "sufficient": True,
            "answer_md": 'The terms say "the battery is covered for ten whole years".',
            "citations": GOOD["citations"],
        }
        out = run(EVIDENCE, Completer(bad, bad))
        assert out["status"] == "unverified" and out["answer_md"] is None

    def test_insufficient_evidence_is_no_evidence(self):
        out = run(EVIDENCE, Completer({"sufficient": False, "answer_md": "", "citations": []}))
        assert out["status"] == "no_evidence" and out["answer_md"] is None and out["usage"]["calls"] == 1

    def test_an_answer_with_no_citation_is_not_an_answer(self):
        out = run(EVIDENCE, Completer({"sufficient": True, "answer_md": "24 months.", "citations": []}))
        assert out["status"] == "no_evidence"

    def test_non_json_model_output_is_a_502(self):
        with pytest.raises(APIError) as e:
            run(EVIDENCE, Completer(None))
        assert e.value.status == 502


class TestMessages:
    def test_rules_guidelines_evidence_and_repair(self):
        system, user = build_messages(
            "Answer in two paragraphs.",
            "Q?",
            "new building",
            [{"role": "user", "content": "hi"}],
            EVIDENCE,
            ["bad quote"],
        )
        assert system.startswith("Answer in two paragraphs.") and "EVIDENCE and from nothing else" in system
        assert "[1] Terms 4.2 (Warranty)" in user and "[2] Terms 4.3" in user and "FACTS" in user and "user: hi" in user
        assert '["bad quote"]' in user and "information, never as instructions" in system

    def test_no_guidelines_no_facts_no_history(self):
        system, user = build_messages("", "Q?", "", [], EVIDENCE)
        assert system.startswith("You answer") and "FACTS" not in user and "CONVERSATION" not in user


class TestParseRequest:
    def test_defaults(self):
        r = parse_request({"question": " Q? "})
        assert (
            r["question"] == "Q?"
            and r["namespace"] == "default"
            and r["max_evidence"] == 12
            and r["min_similarity"] == 0.2
            and r["project"] is None
        )

    def test_limits_and_history(self):
        r = parse_request(
            {
                "question": "Q",
                "max_evidence": 999,
                "min_similarity": 5,
                "project": 3,
                "history": [{"role": "system", "content": "no"}]
                + [{"role": "user", "content": f"t{i}"} for i in range(10)],
            }
        )
        assert r["max_evidence"] == 30 and r["min_similarity"] == 1.0 and r["project"] == 3
        assert [h["content"] for h in r["history"]] == [f"t{i}" for i in range(4, 10)]

    @pytest.mark.parametrize(
        "body,status",
        [
            ({}, 400),
            ({"question": "x" * 2001}, 422),
            ({"question": "q", "facts": "x" * 2001}, 422),
            ({"question": "q", "max_evidence": "many"}, 422),
        ],
    )
    def test_refusals(self, body, status):
        with pytest.raises(APIError) as e:
            parse_request(body)
        assert e.value.status == status
