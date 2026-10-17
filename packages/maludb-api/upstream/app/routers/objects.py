"""
Object endpoints — atomic create + attributes, object detail.

Ports PHP's objects.php and objects_id.php.

An object is created AND its typed attributes applied in ONE transaction:
register the object, then maludb_attributes_apply(kind, id, attributes), then
return maludb_object_get(kind, id).  Either both land or neither does.

Supported kinds for create: 'subject' and 'episode_object'.
maludb_object_get(kind, id) is the canonical handle for any object kind.

Runs in db_tx_core() (register_* + attributes_apply + object_get all need
maludb_core on the search_path).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import Auth
from app.database import db_one, db_tx_core
from app.errors import json_error

router = APIRouter()


# ===========================================================================
# POST /v1/objects/{kind} — atomic create + attributes
# ===========================================================================


@router.post("/v1/objects/{kind}")
async def create_object(kind: str, auth: Auth, request: Request):
    body = await request.json()

    # Validate the optional attributes array up front (no partial writes).
    attributes: list[dict[str, Any]] = []
    if "attributes" in body and body["attributes"] is not None:
        if not isinstance(body["attributes"], list):
            json_error("validation_failed", '"attributes" must be an array of attribute objects.', 422)
        attributes = body["attributes"]

    def _create(conn):
        # ---- 1. create the object via its register_* helper ----
        if kind == "subject":
            name = (
                str(body.get("canonical_name") or body.get("name") or body.get("label") or "").strip()
            )
            if not name:
                json_error("missing_field", 'Field "canonical_name" is required for a subject.', 400)

            type_ = (
                str(body["subject_type"])
                if body.get("subject_type") and str(body.get("subject_type", "")).strip()
                else (
                    str(body["type"])
                    if body.get("type") and str(body.get("type", "")).strip()
                    else "other"
                )
            )
            description = str(body["description"]) if body.get("description") is not None else None
            classifier = str(body["classifier_md"]) if body.get("classifier_md") is not None else None

            row = db_one(
                conn,
                """SELECT register_svpor_subject(
                            p_canonical_name => %s, p_description => %s,
                            p_subject_type => %s, p_classifier_md => %s
                        ) AS id""",
                [name, description, type_, classifier],
            )
            target_id = int(row["id"])  # type: ignore[index]

        elif kind == "episode_object":
            title = str(body.get("title") or "").strip()
            if not title:
                json_error("missing_field", 'Field "title" is required for an episode.', 400)

            ekind = (
                str(body["kind"])
                if body.get("kind") and str(body.get("kind", "")).strip()
                else "activity"
            )
            summary = str(body["summary"]) if body.get("summary") is not None else None
            occurred_at = str(body["occurred_at"]) if body.get("occurred_at") is not None else None
            occurred_until = str(body["occurred_until"]) if body.get("occurred_until") is not None else None
            sensitivity = (
                str(body["sensitivity"])
                if body.get("sensitivity") and str(body.get("sensitivity", "")).strip()
                else "internal"
            )
            provenance = (
                str(body["provenance"])
                if body.get("provenance") and str(body.get("provenance", "")).strip()
                else "provided"
            )
            payload_json = (
                json.dumps(body["payload"])
                if isinstance(body.get("payload"), dict)
                else "{}"
            )

            row = db_one(
                conn,
                """SELECT maludb_register_episode(
                            p_episode_kind => %s, p_title => %s, p_summary => %s,
                            p_payload_jsonb => %s::jsonb,
                            p_occurred_at => %s::timestamptz,
                            p_occurred_until => %s::timestamptz,
                            p_sensitivity => %s, p_provenance => %s
                        ) AS id""",
                [ekind, title, summary, payload_json, occurred_at, occurred_until, sensitivity, provenance],
            )
            target_id = int(row["id"])  # type: ignore[index]

        else:
            json_error(
                "validation_failed",
                f'Unsupported object kind "{kind}" for atomic create (supported: subject, episode_object).',
                422,
            )
            return None  # unreachable, but satisfies type checker

        # ---- 2. apply the typed attributes atomically ----
        if attributes:
            db_one(
                conn,
                "SELECT maludb_attributes_apply(%s, %s, %s::jsonb) AS n",
                [kind, target_id, json.dumps(attributes)],
            )

        # ---- 3. return the assembled handle (object + attributes [+ statements/details]) ----
        got = db_one(conn, "SELECT maludb_object_get(%s, %s) AS obj", [kind, target_id])
        if got and got["obj"] is not None:
            obj = got["obj"]
            if isinstance(obj, str):
                return json.loads(obj)
            return obj  # psycopg may auto-decode jsonb
        return None

    obj = db_tx_core(auth.conn, _create)
    return JSONResponse(status_code=201, content={"object": obj})


# ===========================================================================
# GET /v1/objects/{kind}/{id} — object detail via maludb_object_get()
# ===========================================================================


@router.get("/v1/objects/{kind}/{object_id}")
def get_object(kind: str, object_id: int, auth: Auth):
    def _get(conn):
        row = db_one(conn, "SELECT maludb_object_get(%s, %s) AS obj", [kind, object_id])
        if row is None or row["obj"] is None:
            return None
        obj = row["obj"]
        if isinstance(obj, str):
            return json.loads(obj)
        return obj  # psycopg may auto-decode jsonb

    obj = db_tx_core(auth.conn, _get)
    if obj is None:
        json_error("not_found", "Object not found for the given (kind, id).", 404)

    # maludb_object_get returns a null-object envelope when the handle is unknown.
    if isinstance(obj, dict) and obj.get("object") is None:
        json_error("not_found", "Object not found for the given (kind, id).", 404)

    return {"object": obj}
