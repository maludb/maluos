"""
Principal profiles — the small, standing memory of one agent or one person.

"Sasha always files bills under the vendor's legal name." "Edward wants summaries in three lines."
An agent framework keeps facts like these in a file that rides in the system prompt (Hermes'
MEMORY.md / USER.md). Shared memory needs the same thing server-side: a handful of keyed entries
per principal that can be READ WHOLE in one call and CHANGED.

Changed, not overwritten. MaluDB's doctrine is that a correction never silently destroys history,
so an entry is append-only: every PUT writes a new maludb_memory row (memory_kind 'core_memory')
that names the row it supersedes; the profile is the newest row per key; DELETE writes a tombstone.
The history of any key stays readable. No new table, no extension change — the same table
/v1/notes uses, under a kind of its own, so profile entries never appear as notes or issues.

    GET    /v1/principals/{ref}/profile                  every live entry
    PUT    /v1/principals/{ref}/profile/{key}            {"value": <any JSON>, "note"?: str}
    DELETE /v1/principals/{ref}/profile/{key}
    GET    /v1/principals/{ref}/profile/{key}/history

`ref` is the host's name for the principal ("agent:44", "member:1"). It is a label, not access
control: the tenant token reads every profile in the tenant, and the host decides who may ask.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Request

from app.auth import Auth
from app.database import db_one, db_query, db_tx_core
from app.errors import json_error

router = APIRouter()

KIND = "core_memory"
REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.\-@]{0,119}$")
KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,79}$")
MAX_VALUE_BYTES = 8000  # a profile rides in a system prompt; it is not a document store
MAX_KEYS = 200


def check_ref(ref: str) -> str:
    if not REF.match(ref):
        json_error("validation_failed", "The principal ref may hold letters, digits and : _ . - @ (max 120).", 422)
    return ref


def check_key(key: str) -> str:
    if not KEY.match(key):
        json_error("validation_failed", "A profile key may hold letters, digits and _ . - (max 80).", 422)
    return key


def _entries(auth, ref: str, key: str | None = None) -> list[dict]:
    """Newest row per key; tombstones included so the caller can tell 'deleted' from 'never set'."""
    rows = db_query(
        auth.conn,
        """SELECT DISTINCT ON (payload_jsonb->>'key')
                  memory_id AS id, payload_jsonb->>'key' AS key, payload_jsonb->'value' AS value,
                  (payload_jsonb->>'deleted')::boolean AS deleted, summary AS note,
                  created_at::text AS updated_at
             FROM maludb_memory
            WHERE memory_kind = %s AND payload_jsonb->>'principal' = %s
              AND (%s::text IS NULL OR payload_jsonb->>'key' = %s)
            ORDER BY payload_jsonb->>'key', memory_id DESC""",
        [KIND, ref, key, key],
    )
    for r in rows:  # psycopg already decodes jsonb: a string value arrives as str, not as JSON text
        r["id"] = int(r["id"])
    return rows


def _write(auth, ref: str, key: str, value, note: str | None, deleted: bool) -> dict:
    def _tx(conn):
        previous = db_one(
            conn,
            """SELECT memory_id AS id FROM maludb_memory
                WHERE memory_kind = %s AND payload_jsonb->>'principal' = %s AND payload_jsonb->>'key' = %s
                ORDER BY memory_id DESC LIMIT 1""",
            [KIND, ref, key],
        )
        payload = {
            "principal": ref,
            "key": key,
            "value": value,
            "deleted": deleted,
            "supersedes": int(previous["id"]) if previous else None,
        }
        return db_one(
            conn,
            """INSERT INTO maludb_memory (memory_kind, title, summary, payload_jsonb, recorded_at)
               VALUES (%s, %s, %s, %s::jsonb, now())
               RETURNING memory_id AS id, created_at::text AS updated_at""",
            [KIND, f"{ref} · {key}", note, json.dumps(payload)],
        ) | {"supersedes": payload["supersedes"]}

    return db_tx_core(auth.conn, _tx)


@router.get("/v1/principals/{ref}/profile")
def get_profile(auth: Auth, ref: str):
    check_ref(ref)
    live = [e for e in _entries(auth, ref) if not e["deleted"]]
    return {
        "principal": ref,
        "entries": {
            e["key"]: {"value": e["value"], "note": e["note"], "updated_at": e["updated_at"], "id": e["id"]}
            for e in live
        },
    }


@router.put("/v1/principals/{ref}/profile/{key}")
async def put_profile_entry(auth: Auth, ref: str, key: str, request: Request):
    check_ref(ref)
    check_key(key)
    body = await request.json()
    if not isinstance(body, dict) or "value" not in body or body["value"] is None:
        json_error(
            "missing_field", 'Field "value" is required (any JSON but null; use DELETE to remove an entry).', 400
        )
    if len(json.dumps(body["value"]).encode()) > MAX_VALUE_BYTES:
        json_error("validation_failed", f"A profile value may be at most {MAX_VALUE_BYTES} bytes of JSON.", 422)
    current = _entries(auth, ref)
    if (
        key not in {e["key"] for e in current if not e["deleted"]}
        and sum(1 for e in current if not e["deleted"]) >= MAX_KEYS
    ):
        json_error("validation_failed", f"A profile holds at most {MAX_KEYS} entries.", 422)
    note = str(body["note"]).strip() if body.get("note") is not None and str(body["note"]).strip() else None
    written = _write(auth, ref, key, body["value"], note, deleted=False)
    return {
        "principal": ref,
        "key": key,
        "value": body["value"],
        "id": int(written["id"]),
        "supersedes": written["supersedes"],
        "updated_at": written["updated_at"],
    }


@router.delete("/v1/principals/{ref}/profile/{key}")
def delete_profile_entry(auth: Auth, ref: str, key: str):
    check_ref(ref)
    check_key(key)
    existing = _entries(auth, ref, key)
    if not existing or existing[0]["deleted"]:
        json_error("not_found", "That profile entry does not exist.", 404)
    written = _write(auth, ref, key, None, None, deleted=True)
    return {
        "principal": ref,
        "key": key,
        "deleted": True,
        "id": int(written["id"]),
        "supersedes": written["supersedes"],
    }


@router.get("/v1/principals/{ref}/profile/{key}/history")
def profile_entry_history(auth: Auth, ref: str, key: str):
    check_ref(ref)
    check_key(key)
    rows = db_query(
        auth.conn,
        """SELECT memory_id AS id, payload_jsonb->'value' AS value, (payload_jsonb->>'deleted')::boolean AS deleted,
                  (payload_jsonb->>'supersedes')::bigint AS supersedes, summary AS note, created_at::text AS at
             FROM maludb_memory
            WHERE memory_kind = %s AND payload_jsonb->>'principal' = %s AND payload_jsonb->>'key' = %s
            ORDER BY memory_id DESC LIMIT 200""",
        [KIND, ref, key],
    )
    for r in rows:
        r["id"] = int(r["id"])
    return {"principal": ref, "key": key, "history": rows}
