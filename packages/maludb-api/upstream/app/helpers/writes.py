"""
Helpers for write endpoints that accept either a single object or a JSON array.

PostgREST lets clients POST one row (a JSON object) or many (a JSON array) to the
same collection endpoint. ``as_items`` normalizes the parsed request body into a
uniform list plus an ``is_batch`` flag so a handler can create every item in one
transaction and shape the response accordingly (single object vs. array).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import psycopg

from app.errors import json_error


def as_items(body: object) -> tuple[list[dict], bool]:
    """Normalize a parsed JSON body into ``(items, is_batch)``.

    - a JSON object → ``([body], False)`` — single-row create (back-compatible)
    - a JSON array  → ``(body, True)`` — bulk create; every element must be an object

    Raises ``422 validation_failed`` if the body is neither, or if any batch
    element is not a JSON object.
    """
    if isinstance(body, dict):
        return [body], False
    if isinstance(body, list):
        for i, item in enumerate(body):
            if not isinstance(item, dict):
                json_error("validation_failed", f"Batch item {i} must be a JSON object.", 422)
        return body, True
    json_error("validation_failed", "Request body must be a JSON object or an array of objects.", 422)
    raise AssertionError("unreachable")  # json_error always raises; satisfies type checkers


def tx_with_advisory_lock(
    conn: psycopg.Connection,
    lock_name: str,
    fn: Callable[[psycopg.Connection], Any],
) -> Any:
    """Run ``fn(conn)`` in a transaction holding a per-name advisory lock.

    Serializes id generation for tables whose ids are derived as ``MAX(id)+1``
    (no sequence): concurrent inserters block on ``pg_advisory_xact_lock`` until
    the holder commits, so ids can't collide — for a single row or a whole batch.
    The lock auto-releases at transaction end.

    Use the **table** name as ``lock_name`` so endpoints that share a table
    serialize together (e.g. ``/v1/subjects`` and ``/v1/projects`` both insert
    into ``maludb_subject`` and must contend for the same lock).
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)", [lock_name])
        return fn(conn)
