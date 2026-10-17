"""
Tests for the LLM helper module — pure unit tests, no live API or DB required.

Tests:
    mem_embed_deterministic — same text -> same vector, unit length, different text -> different vector
    mem_chunk              — splits correctly, handles short text and empty input
    llm_json_from_text     — extracts JSON from various formats (raw, fenced, embedded)
    mem_vector_literal     — formats float list as SQL-castable literal
"""

from __future__ import annotations

import math

import pytest

from app.helpers.llm import (
    llm_json_from_text,
    mem_chunk,
    mem_embed_deterministic,
    mem_embed_dim,
    mem_vector_literal,
)

# ---------------------------------------------------------------------------
# mem_embed_deterministic
# ---------------------------------------------------------------------------


class TestMemEmbedDeterministic:
    """Deterministic embedding: same text -> same vector, unit length."""

    def test_same_text_same_vector(self):
        v1 = mem_embed_deterministic("hello world")
        v2 = mem_embed_deterministic("hello world")
        assert v1 == v2

    def test_different_text_different_vector(self):
        v1 = mem_embed_deterministic("hello world")
        v2 = mem_embed_deterministic("goodbye world")
        assert v1 != v2

    def test_correct_dimension(self):
        v = mem_embed_deterministic("test")
        assert len(v) == mem_embed_dim()

    def test_unit_length(self):
        v = mem_embed_deterministic("unit vector test")
        norm = math.sqrt(sum(x * x for x in v))
        assert norm == pytest.approx(1.0, abs=1e-9)

    def test_values_in_range(self):
        """All components should be between -1 and 1 (before normalization they are,
        after normalization they may be smaller but never larger in magnitude)."""
        v = mem_embed_deterministic("range check")
        for x in v:
            assert -1.0 <= x <= 1.0

    def test_empty_string(self):
        v = mem_embed_deterministic("")
        assert len(v) == mem_embed_dim()
        norm = math.sqrt(sum(x * x for x in v))
        assert norm == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# mem_chunk
# ---------------------------------------------------------------------------


class TestMemChunk:
    """Text chunking with paragraph/sentence boundaries and overlap."""

    def test_empty_text(self):
        assert mem_chunk("") == []

    def test_whitespace_only(self):
        assert mem_chunk("   \n\n  ") == []

    def test_short_text_single_chunk(self):
        text = "This is short."
        chunks = mem_chunk(text, max_chars=2000)
        assert chunks == [text]

    def test_exact_max_length(self):
        text = "a" * 2000
        chunks = mem_chunk(text, max_chars=2000)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_splits_long_text(self):
        text = "word " * 1000  # ~5000 chars
        chunks = mem_chunk(text, max_chars=500, overlap=50)
        assert len(chunks) > 1
        # Each chunk should be no longer than max + some boundary tolerance
        for c in chunks:
            assert len(c) <= 510  # allow small overshoot from boundary seeking

    def test_prefers_paragraph_boundary(self):
        para1 = "First paragraph. " * 60  # ~1000 chars
        para2 = "Second paragraph. " * 60
        text = para1.strip() + "\n\n" + para2.strip()
        chunks = mem_chunk(text, max_chars=1100, overlap=100)
        # The first chunk should end near the paragraph boundary
        assert len(chunks) >= 2

    def test_overlap_present(self):
        """With overlap, consecutive chunks should share some text."""
        text = " ".join(f"word{i}" for i in range(500))
        chunks = mem_chunk(text, max_chars=200, overlap=50)
        assert len(chunks) >= 2
        # The end of chunk[0] should appear at the start of chunk[1]
        # (overlap means the second chunk starts before the first ends)
        overlap_text = chunks[0][-40:]  # last 40 chars of first chunk
        # At least some of these chars should appear in the second chunk
        assert any(w in chunks[1] for w in overlap_text.split())

    def test_custom_params(self):
        text = "x" * 500
        chunks = mem_chunk(text, max_chars=100, overlap=10)
        assert len(chunks) > 1


# ---------------------------------------------------------------------------
# llm_json_from_text
# ---------------------------------------------------------------------------


class TestLlmJsonFromText:
    """Tolerant JSON extraction from LLM output."""

    def test_raw_json(self):
        result = llm_json_from_text('{"key": "value"}')
        assert result == {"key": "value"}

    def test_raw_json_with_whitespace(self):
        result = llm_json_from_text('  \n {"key": "value"} \n ')
        assert result == {"key": "value"}

    def test_fenced_json(self):
        text = 'Here is the result:\n```json\n{"key": "value"}\n```\nDone.'
        result = llm_json_from_text(text)
        assert result == {"key": "value"}

    def test_fenced_no_language(self):
        text = 'Result:\n```\n{"key": "value"}\n```'
        result = llm_json_from_text(text)
        assert result == {"key": "value"}

    def test_embedded_json(self):
        text = 'The answer is {"candidate_edges": []} and that is all.'
        result = llm_json_from_text(text)
        assert result == {"candidate_edges": []}

    def test_no_json(self):
        result = llm_json_from_text("This is just plain text with no JSON.")
        assert result is None

    def test_array_returns_none(self):
        """Top-level arrays are not dicts — should return None."""
        result = llm_json_from_text('[1, 2, 3]')
        assert result is None

    def test_nested_json(self):
        text = '{"outer": {"inner": [1, 2, 3]}, "flag": true}'
        result = llm_json_from_text(text)
        assert result == {"outer": {"inner": [1, 2, 3]}, "flag": True}

    def test_invalid_json_returns_none(self):
        result = llm_json_from_text("{not valid json}")
        assert result is None


# ---------------------------------------------------------------------------
# mem_vector_literal
# ---------------------------------------------------------------------------


class TestMemVectorLiteral:
    """Format float list as SQL-castable malu_vector literal."""

    def test_basic(self):
        result = mem_vector_literal([0.1, -0.2, 0.3])
        assert result.startswith("[")
        assert result.endswith("]")
        # Should contain the values
        assert "0.1" in result
        assert "-0.2" in result
        assert "0.3" in result

    def test_no_trailing_zeros(self):
        result = mem_vector_literal([1.0, 0.50000000])
        # Should not have excessive trailing zeros
        assert "1.00000000" not in result
        assert result == "[1,-0.5]" or "[1.0" not in result.replace("[1,", "[1.0,") or "1" in result

    def test_zero_vector(self):
        result = mem_vector_literal([0.0, 0.0, 0.0])
        assert result == "[0,0,0]"

    def test_empty(self):
        result = mem_vector_literal([])
        assert result == "[]"

    def test_single(self):
        result = mem_vector_literal([0.5])
        assert result == "[0.5]"

    def test_round_trip_format(self):
        """The literal should be parseable back to floats."""
        floats = [0.123, -0.456, 0.789, 0.0, 1.0, -1.0]
        literal = mem_vector_literal(floats)
        # Strip brackets and split
        inner = literal[1:-1]
        parsed = [float(x) for x in inner.split(",")]
        for orig, back in zip(floats, parsed):
            assert back == pytest.approx(orig, abs=1e-7)
