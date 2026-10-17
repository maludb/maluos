"""
Tests for app.helpers.query — the PostgREST-compatible query parser.

Pure unit tests: build a QuerySpec, feed it Starlette QueryParams, and assert on
the generated SQL fragments + bound params. No database connection required.
"""

from __future__ import annotations

import pytest
from starlette.datastructures import QueryParams

import app.database
from app.errors import APIError
from app.helpers.query import Col, QuerySpec, content_range, parse_query, resolve_total, wants_count

# A representative spec covering int / str / bool columns plus a computed column.
SPEC = QuerySpec(
    columns={
        "id": Col("s.subject_id", int),
        "label": Col("s.canonical_name", str),
        "type": Col("s.subject_type", str),
        "active": Col("s.active", bool),
        "score": Col("s.score", float),
        "linked": Col("(SELECT count(*) FROM x WHERE x.sid = s.subject_id)", int),
    },
    default_order=[("label", "asc")],
    default_limit=50,
    max_limit=200,
)


def qp(s: str) -> QueryParams:
    return QueryParams(s)


def run(s: str, **kw):
    return parse_query(qp(s), SPEC, **kw)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_empty_query_uses_defaults(self):
        r = run("")
        assert r.where_sql == ""
        assert r.where_params == []
        assert r.order_sql == "ORDER BY s.canonical_name ASC"
        assert r.limit_sql == "LIMIT %s"
        assert r.limit_params == [50]

    def test_default_select_is_all_columns_in_order(self):
        r = run("")
        assert r.select_list.startswith("s.subject_id AS id, s.canonical_name AS label")
        assert "AS linked" in r.select_list
        assert r.selected[0] == "id"

    def test_limit_over_max_raises_422(self):
        with pytest.raises(APIError) as e:
            run("limit=9999")
        assert e.value.status == 422
        assert e.value.code == "validation_failed"

    def test_offset_appended_only_when_nonzero(self):
        assert run("offset=0").limit_sql == "LIMIT %s"
        r = run("limit=10&offset=20")
        assert r.limit_sql == "LIMIT %s OFFSET %s"
        assert r.limit_params == [10, 20]


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


class TestFilters:
    def test_eq(self):
        r = run("type=eq.person")
        assert r.where_sql == "WHERE s.subject_type = %s"
        assert r.where_params == ["person"]

    def test_int_coercion(self):
        r = run("id=eq.42")
        assert r.where_params == [42]
        assert isinstance(r.where_params[0], int)

    def test_invalid_int_raises(self):
        with pytest.raises(APIError) as e:
            run("id=eq.abc")
        assert e.value.status == 400
        assert e.value.code == "bad_request"

    def test_comparison_operators(self):
        assert run("id=gte.5").where_sql == "WHERE s.subject_id >= %s"
        assert run("id=lt.5").where_sql == "WHERE s.subject_id < %s"

    def test_multiple_filters_are_anded(self):
        r = run("id=gte.5&id=lte.10")
        assert r.where_sql == "WHERE s.subject_id >= %s AND s.subject_id <= %s"
        assert r.where_params == [5, 10]

    def test_like_translates_star_to_percent(self):
        r = run("label=ilike.*foo*")
        assert r.where_sql == "WHERE s.canonical_name ILIKE %s"
        assert r.where_params == ["%foo%"]

    def test_in_list(self):
        r = run("id=in.(1,2,3)")
        assert r.where_sql == "WHERE s.subject_id IN (%s, %s, %s)"
        assert r.where_params == [1, 2, 3]

    def test_is_null(self):
        r = run("label=is.null")
        assert r.where_sql == "WHERE s.canonical_name IS NULL"
        assert r.where_params == []

    def test_is_true(self):
        assert run("active=is.true").where_sql == "WHERE s.active IS TRUE"

    def test_is_rejects_bad_value(self):
        with pytest.raises(APIError):
            run("active=is.maybe")

    def test_negation(self):
        r = run("type=not.eq.person")
        assert r.where_sql == "WHERE NOT (s.subject_type = %s)"
        assert r.where_params == ["person"]

    def test_negated_is_null(self):
        assert run("label=not.is.null").where_sql == "WHERE NOT (s.canonical_name IS NULL)"

    def test_unknown_key_is_ignored(self):
        # Unknown keys (typos, ?debug=1, cache-busters) are ignored, not rejected.
        r = run("nope=whatever")
        assert r.where_sql == ""
        assert r.where_params == []

    def test_debug_param_ignored(self):
        assert run("debug=1").where_sql == ""

    def test_bare_value_is_implicit_eq(self):
        r = run("type=person")
        assert r.where_sql == "WHERE s.subject_type = %s"
        assert r.where_params == ["person"]

    def test_bare_value_implicit_eq_coerces_int(self):
        r = run("id=42")
        assert r.where_sql == "WHERE s.subject_id = %s"
        assert r.where_params == [42]

    def test_dotted_literal_value_is_implicit_eq(self):
        # A value with dots but no leading operator token is an exact match.
        r = run("label=2025-01-01T00:00:00.000Z")
        assert r.where_sql == "WHERE s.canonical_name = %s"
        assert r.where_params == ["2025-01-01T00:00:00.000Z"]

    def test_text_operator_on_non_text_column_raises(self):
        with pytest.raises(APIError) as e:
            run("id=ilike.*5*")
        assert e.value.status == 400

    def test_fts_on_non_text_column_raises(self):
        with pytest.raises(APIError):
            run("id=fts.x")

    def test_invalid_int_value_still_raises(self):
        with pytest.raises(APIError):
            run("id=zzz.1")  # implicit eq → int('zzz.1') fails coercion

    def test_reserved_param_not_treated_as_filter(self):
        r = run("q=hello", reserved=("q",))
        assert r.where_sql == ""


# ---------------------------------------------------------------------------
# Full-text search
# ---------------------------------------------------------------------------


class TestFts:
    def test_fts_no_language(self):
        r = run("label=fts.cat")
        assert r.where_sql == "WHERE to_tsvector(s.canonical_name) @@ to_tsquery(%s)"
        assert r.where_params == ["cat"]

    def test_fts_with_language(self):
        r = run("label=plfts(english).cat dog")
        assert r.where_sql == "WHERE to_tsvector(%s, s.canonical_name) @@ plainto_tsquery(%s, %s)"
        assert r.where_params == ["english", "english", "cat dog"]


# ---------------------------------------------------------------------------
# OR groups
# ---------------------------------------------------------------------------


class TestOrGroups:
    def test_simple_or(self):
        r = run("or=(id.eq.1,id.eq.2)")
        assert r.where_sql == "WHERE (s.subject_id = %s OR s.subject_id = %s)"
        assert r.where_params == [1, 2]

    def test_or_anded_with_filter(self):
        r = run("type=eq.person&or=(id.eq.1,id.eq.2)")
        assert r.where_sql == "WHERE s.subject_type = %s AND (s.subject_id = %s OR s.subject_id = %s)"
        assert r.where_params == ["person", 1, 2]

    def test_or_unknown_column_raises(self):
        with pytest.raises(APIError):
            run("or=(nope.eq.1,id.eq.2)")

    def test_and_group(self):
        r = run("and=(id.eq.1,type.eq.person)")
        assert r.where_sql == "WHERE (s.subject_id = %s AND s.subject_type = %s)"
        assert r.where_params == [1, "person"]

    def test_and_group_bare_values(self):
        r = run("and=(id.7,type.person)")
        assert r.where_sql == "WHERE (s.subject_id = %s AND s.subject_type = %s)"
        assert r.where_params == [7, "person"]


# ---------------------------------------------------------------------------
# Select projection
# ---------------------------------------------------------------------------


class TestSelect:
    def test_select_subset(self):
        r = run("select=id,label")
        assert r.select_list == "s.subject_id AS id, s.canonical_name AS label"
        assert r.selected == ["id", "label"]

    def test_select_alias(self):
        r = run("select=name:label")
        assert r.select_list == "s.canonical_name AS name"
        assert r.selected == ["name"]

    def test_select_unknown_column_raises(self):
        with pytest.raises(APIError):
            run("select=id,bogus")

    def test_select_rejects_injection_alias(self):
        with pytest.raises(APIError):
            run("select=label:label;DROP")  # alias 'label;DROP'? -> alias before ':' is 'label', name 'label;DROP'

    def test_select_rejects_bad_alias_chars(self):
        with pytest.raises(APIError):
            run("select=bad-alias:label")


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


class TestOrder:
    def test_single_desc(self):
        assert run("order=label.desc").order_sql == "ORDER BY s.canonical_name DESC"

    def test_multi_key(self):
        r = run("order=type.asc,id.desc")
        assert r.order_sql == "ORDER BY s.subject_type ASC, s.subject_id DESC"

    def test_nulls_last(self):
        assert run("order=label.desc.nullslast").order_sql == "ORDER BY s.canonical_name DESC NULLS LAST"

    def test_unknown_column_raises(self):
        with pytest.raises(APIError):
            run("order=bogus.asc")

    def test_bad_modifier_raises(self):
        with pytest.raises(APIError):
            run("order=label.sideways")


# ---------------------------------------------------------------------------
# Pagination errors
# ---------------------------------------------------------------------------


class TestPagination:
    def test_non_integer_limit_raises(self):
        with pytest.raises(APIError):
            run("limit=ten")

    def test_negative_offset_raises(self):
        with pytest.raises(APIError):
            run("offset=-1")

    def test_exposes_limit_and_offset(self):
        r = run("limit=25&offset=50")
        assert r.limit == 25
        assert r.offset == 50

    def test_default_offset_is_zero(self):
        assert run("").offset == 0


# ---------------------------------------------------------------------------
# Count / Content-Range helpers
# ---------------------------------------------------------------------------


class _Req:
    """Minimal stand-in for a Starlette Request (only .headers is used)."""

    def __init__(self, prefer: str = ""):
        self.headers = {"prefer": prefer}


class TestWantsCount:
    def test_absent(self):
        assert wants_count(_Req()) is None

    def test_exact(self):
        assert wants_count(_Req("count=exact")) == "exact"

    def test_planned_among_other_prefs(self):
        assert wants_count(_Req("return=representation, count=planned")) == "planned"

    def test_estimated(self):
        assert wants_count(_Req("count=estimated")) == "estimated"

    def test_unknown_value_ignored(self):
        assert wants_count(_Req("count=bogus")) is None


class TestContentRange:
    def test_unknown_total(self):
        assert content_range(0, 10, None) == "0-9/*"

    def test_with_total_and_offset(self):
        assert content_range(20, 5, 57) == "20-24/57"

    def test_empty_page_known_total(self):
        assert content_range(0, 0, 0) == "*/0"

    def test_empty_page_unknown_total(self):
        assert content_range(40, 0, None) == "*/*"


class TestResolveTotal:
    """resolve_total() with db_one monkeypatched — no real database."""

    def test_no_count_kind_returns_none_without_querying(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("db_one should not be called when count_kind is None")

        monkeypatch.setattr(app.database, "db_one", _boom)
        assert resolve_total(object(), None, "maludb_subject s", "", []) is None

    def test_exact_runs_count(self, monkeypatch):
        captured = {}

        def _fake_one(conn, sql, params):
            captured["sql"] = sql
            return {"n": 42}

        monkeypatch.setattr(app.database, "db_one", _fake_one)
        assert resolve_total(object(), "exact", "maludb_subject s", "WHERE x = %s", [1]) == 42
        assert "count(*)" in captured["sql"]
        assert "FROM maludb_subject s WHERE x = %s" in captured["sql"]

    def test_planned_reads_plan_rows(self, monkeypatch):
        def _fake_one(conn, sql, params):
            assert sql.startswith("EXPLAIN (FORMAT JSON)")
            return {"QUERY PLAN": [{"Plan": {"Plan Rows": 99}}]}

        monkeypatch.setattr(app.database, "db_one", _fake_one)
        assert resolve_total(object(), "planned", "maludb_subject s", "", []) == 99

    def test_planned_handles_json_string(self, monkeypatch):
        def _fake_one(conn, sql, params):
            return {"QUERY PLAN": '[{"Plan": {"Plan Rows": 7}}]'}

        monkeypatch.setattr(app.database, "db_one", _fake_one)
        assert resolve_total(object(), "estimated", "maludb_subject s", "", []) == 7
