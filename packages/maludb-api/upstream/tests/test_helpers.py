"""
Tests for the shared helper modules — shape_statement and shape_attribute.

Pure unit tests using mock data; no database connection required.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.helpers.attributes import ATTRIBUTE_COLS, shape_attribute
from app.helpers.statements import STATEMENT_COLS, shape_statement

# ---------------------------------------------------------------------------
# shape_statement
# ---------------------------------------------------------------------------

class TestShapeStatement:
    """Tests for shape_statement() — in-place type normalization."""

    def _make_row(self, **overrides) -> dict:
        """Return a realistic statement row (all values as strings, like raw DB output)."""
        row = {
            "id": "42",
            "subject_kind": "subject",
            "subject_id": "7",
            "verb_id": "3",
            "object_kind": "episode",
            "object_id": "100",
            "predicate_id": "5",
            "valid_from": "2025-01-01T00:00:00+00:00",
            "valid_to": None,
            "confidence": "0.95",
            "provenance": "provided",
            "source_package_id": "12",
            "metadata": '{"key": "value"}',
            "created_at": "2025-06-01T12:00:00+00:00",
        }
        row.update(overrides)
        return row

    def test_casts_integer_columns(self):
        row = self._make_row()
        shape_statement(row)
        assert row["id"] == 42
        assert isinstance(row["id"], int)
        assert row["subject_id"] == 7
        assert isinstance(row["subject_id"], int)
        assert row["verb_id"] == 3
        assert isinstance(row["verb_id"], int)
        assert row["object_id"] == 100
        assert isinstance(row["object_id"], int)
        assert row["predicate_id"] == 5
        assert isinstance(row["predicate_id"], int)
        assert row["source_package_id"] == 12
        assert isinstance(row["source_package_id"], int)

    def test_casts_confidence_to_float(self):
        row = self._make_row(confidence="0.85")
        shape_statement(row)
        assert row["confidence"] == 0.85
        assert isinstance(row["confidence"], float)

    def test_decodes_metadata_json_string(self):
        row = self._make_row(metadata='{"foo": "bar", "n": 1}')
        shape_statement(row)
        assert row["metadata"] == {"foo": "bar", "n": 1}
        assert isinstance(row["metadata"], dict)

    def test_metadata_already_decoded_dict(self):
        """psycopg v3 may auto-decode jsonb — shape_statement should leave it as-is."""
        row = self._make_row(metadata={"already": "decoded"})
        shape_statement(row)
        assert row["metadata"] == {"already": "decoded"}
        assert isinstance(row["metadata"], dict)

    def test_null_integer_columns(self):
        row = self._make_row(
            predicate_id=None,
            source_package_id=None,
        )
        shape_statement(row)
        assert row["predicate_id"] is None
        assert row["source_package_id"] is None

    def test_null_confidence(self):
        row = self._make_row(confidence=None)
        shape_statement(row)
        assert row["confidence"] is None

    def test_null_metadata(self):
        row = self._make_row(metadata=None)
        shape_statement(row)
        assert row["metadata"] is None

    def test_empty_metadata_object(self):
        row = self._make_row(metadata="{}")
        shape_statement(row)
        assert row["metadata"] == {}

    def test_preserves_non_cast_fields(self):
        row = self._make_row()
        shape_statement(row)
        assert row["subject_kind"] == "subject"
        assert row["object_kind"] == "episode"
        assert row["provenance"] == "provided"
        assert row["valid_from"] == "2025-01-01T00:00:00+00:00"
        assert row["valid_to"] is None
        assert row["created_at"] == "2025-06-01T12:00:00+00:00"

    def test_handles_decimal_values(self):
        """psycopg v3 may return Decimal for numeric columns."""
        row = self._make_row(
            id=Decimal("42"),
            confidence=Decimal("0.75"),
        )
        shape_statement(row)
        assert row["id"] == 42
        assert isinstance(row["id"], int)
        assert row["confidence"] == 0.75
        assert isinstance(row["confidence"], float)

    def test_statement_cols_contains_expected_aliases(self):
        assert "statement_id AS id" in STATEMENT_COLS
        assert "metadata_jsonb AS metadata" in STATEMENT_COLS
        assert "subject_kind" in STATEMENT_COLS
        assert "created_at" in STATEMENT_COLS


# ---------------------------------------------------------------------------
# shape_attribute
# ---------------------------------------------------------------------------

class TestShapeAttribute:
    """Tests for shape_attribute() — in-place type normalization."""

    def _make_row(self, **overrides) -> dict:
        """Return a realistic attribute row (all values as strings, like raw DB output)."""
        row = {
            "id": "99",
            "target_kind": "episode",
            "target_id": "50",
            "attr_name": "duration_minutes",
            "value_timestamp": None,
            "value_range": None,
            "value_numeric": "42.5",
            "value_text": None,
            "value_jsonb": '{"nested": true}',
            "unit": "minutes",
            "provenance": "provided",
            "confidence": "0.9",
            "valid_from": "2025-01-01T00:00:00+00:00",
            "valid_to": None,
            "metadata": '{"source": "import"}',
            "created_at": "2025-06-01T12:00:00+00:00",
            "ref_source": None,
            "ref_entity": None,
            "ref_key": None,
        }
        row.update(overrides)
        return row

    def test_casts_integer_columns(self):
        row = self._make_row()
        shape_attribute(row)
        assert row["id"] == 99
        assert isinstance(row["id"], int)
        assert row["target_id"] == 50
        assert isinstance(row["target_id"], int)

    def test_casts_float_columns(self):
        row = self._make_row(value_numeric="3.14", confidence="0.99")
        shape_attribute(row)
        assert row["value_numeric"] == pytest.approx(3.14)
        assert isinstance(row["value_numeric"], float)
        assert row["confidence"] == pytest.approx(0.99)
        assert isinstance(row["confidence"], float)

    def test_decodes_value_jsonb_string(self):
        row = self._make_row(value_jsonb='{"a": 1}')
        shape_attribute(row)
        assert row["value_jsonb"] == {"a": 1}
        assert isinstance(row["value_jsonb"], dict)

    def test_value_jsonb_already_decoded(self):
        row = self._make_row(value_jsonb={"already": "decoded"})
        shape_attribute(row)
        assert row["value_jsonb"] == {"already": "decoded"}

    def test_decodes_metadata_string(self):
        row = self._make_row(metadata='{"m": true}')
        shape_attribute(row)
        assert row["metadata"] == {"m": True}

    def test_metadata_already_decoded(self):
        row = self._make_row(metadata={"already": "decoded"})
        shape_attribute(row)
        assert row["metadata"] == {"already": "decoded"}

    def test_null_integer_columns(self):
        row = self._make_row(id=None, target_id=None)
        shape_attribute(row)
        assert row["id"] is None
        assert row["target_id"] is None

    def test_null_float_columns(self):
        row = self._make_row(value_numeric=None, confidence=None)
        shape_attribute(row)
        assert row["value_numeric"] is None
        assert row["confidence"] is None

    def test_null_json_columns(self):
        row = self._make_row(value_jsonb=None, metadata=None)
        shape_attribute(row)
        assert row["value_jsonb"] is None
        assert row["metadata"] is None

    def test_preserves_non_cast_fields(self):
        row = self._make_row()
        shape_attribute(row)
        assert row["target_kind"] == "episode"
        assert row["attr_name"] == "duration_minutes"
        assert row["unit"] == "minutes"
        assert row["provenance"] == "provided"
        assert row["valid_from"] == "2025-01-01T00:00:00+00:00"
        assert row["valid_to"] is None
        assert row["created_at"] == "2025-06-01T12:00:00+00:00"
        assert row["ref_source"] is None
        assert row["ref_entity"] is None
        assert row["ref_key"] is None

    def test_value_range_left_as_text(self):
        row = self._make_row(value_range='["2025-01-01","2025-12-31")')
        shape_attribute(row)
        assert row["value_range"] == '["2025-01-01","2025-12-31")'

    def test_handles_decimal_values(self):
        """psycopg v3 may return Decimal for numeric columns."""
        row = self._make_row(
            id=Decimal("99"),
            value_numeric=Decimal("42.5"),
            confidence=Decimal("0.9"),
        )
        shape_attribute(row)
        assert row["id"] == 99
        assert isinstance(row["id"], int)
        assert row["value_numeric"] == pytest.approx(42.5)
        assert isinstance(row["value_numeric"], float)
        assert row["confidence"] == pytest.approx(0.9)
        assert isinstance(row["confidence"], float)

    def test_attribute_cols_contains_expected_aliases(self):
        assert "attribute_id AS id" in ATTRIBUTE_COLS
        assert "metadata_jsonb AS metadata" in ATTRIBUTE_COLS
        assert "target_kind" in ATTRIBUTE_COLS
        assert "ref_source" in ATTRIBUTE_COLS
        assert "ref_entity" in ATTRIBUTE_COLS
        assert "ref_key" in ATTRIBUTE_COLS
