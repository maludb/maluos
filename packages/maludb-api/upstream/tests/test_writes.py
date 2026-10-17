"""
Tests for app.helpers.writes.as_items — the single-object / JSON-array normalizer
used by the bulk create endpoints. Pure unit tests; no database connection.
"""

from __future__ import annotations

import pytest

from app.errors import APIError
from app.helpers.writes import as_items, tx_with_advisory_lock


class TestAsItems:
    def test_single_object(self):
        body = {"a": 1}
        items, is_batch = as_items(body)
        assert items == [body]
        assert is_batch is False

    def test_array_of_objects(self):
        body = [{"a": 1}, {"b": 2}]
        items, is_batch = as_items(body)
        assert items == body
        assert is_batch is True

    def test_empty_array_is_batch(self):
        items, is_batch = as_items([])
        assert items == []
        assert is_batch is True

    def test_array_with_non_object_item_raises(self):
        with pytest.raises(APIError) as e:
            as_items([{"a": 1}, "nope"])
        assert e.value.status == 422
        assert e.value.code == "validation_failed"
        assert "item 1" in e.value.message

    @pytest.mark.parametrize("bad", ["a string", 42, 3.14, True, None])
    def test_non_object_non_array_raises(self, bad):
        with pytest.raises(APIError) as e:
            as_items(bad)
        assert e.value.status == 422
        assert e.value.code == "validation_failed"


class _FakeCursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.log.append((sql, params))


class _FakeConn:
    """Duck-typed psycopg connection recording executed SQL; never touches a DB."""

    def __init__(self):
        self.log: list = []

    def transaction(self):
        return _FakeCursor(self.log)  # reused as a no-op context manager

    def cursor(self):
        return _FakeCursor(self.log)


class TestTxWithAdvisoryLock:
    def test_acquires_lock_and_runs_fn(self):
        conn = _FakeConn()
        result = tx_with_advisory_lock(conn, "maludb_subject", lambda c: "done")
        assert result == "done"
        assert conn.log, "expected the advisory-lock SQL to be issued"
        sql, params = conn.log[0]
        assert "pg_advisory_xact_lock" in sql
        assert params == ["maludb_subject"]

    def test_propagates_errors_from_fn(self):
        conn = _FakeConn()

        def boom(_conn):
            raise ValueError("kaboom")

        with pytest.raises(ValueError):
            tx_with_advisory_lock(conn, "maludb_verb", boom)
