"""
Skill routes a fleet of agents needs — additive to skills.py, which is untouched.

A host that distributes skills to many agents has three needs the existing routes do not meet:

  GET /v1/skills/resolve?name=…[&bundle_hash=…|&version=…]
        Name resolution with a PIN. Until now a name resolved only to "the newest enabled row", so
        a host could not say "the version this agent was evaluated against". bundle_hash is the
        true identity of a bundle (sha256 over its files); version is the human label. A pinned
        lookup returns the row even when it has since been disabled — a pin is a statement about
        the past, and `enabled` in the answer says whether it is still current.
  GET /v1/skills/{id}/files
        The file listing without any content — what a sync needs to decide it already has a bundle.
  GET /v1/skills/{id}/files/{path}
        ONE file. /bundle returns every file base64-encoded in one response, so progressive
        disclosure of a references/ folder meant pulling the whole bundle first, and the MCP
        get_skill tool could list reference files but never read one.

Retiring a skill is already PATCH {"enabled": false} — the designed supersession signal. DELETE
stays the hard delete it is in the PHP contract; a host distributing skills should never call it.

This router is mounted BEFORE skills.py so that /v1/skills/resolve is not read as /v1/skills/{id}.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter

from app.auth import Auth
from app.database import db_one, db_query
from app.errors import json_error

router = APIRouter()

_SKILL_COLUMNS = """skill_id AS id, skill_name AS name, description, version, visibility, enabled, bundle_hash,
                    source_owner_schema, source_skill_id,
                    created_at::text AS created_at, updated_at::text AS updated_at"""


def _shape(skill: dict) -> dict:
    skill["id"] = int(skill["id"])
    if skill.get("source_skill_id") is not None:
        skill["source_skill_id"] = int(skill["source_skill_id"])
    skill["enabled"] = None if skill["enabled"] is None else bool(skill["enabled"])
    return skill


@router.get("/v1/skills/resolve")
def resolve_skill(auth: Auth, name: str = "", bundle_hash: str | None = None, version: str | None = None):
    name = name.strip()
    if not name:
        json_error("missing_field", 'Query parameter "name" is required.', 400)
    if bundle_hash and version:
        json_error("validation_failed", 'Pin by "bundle_hash" or by "version", not both.', 422)
    if bundle_hash:
        skill = db_one(
            auth.conn,
            f"SELECT {_SKILL_COLUMNS} FROM maludb_skill WHERE skill_name = %s AND bundle_hash = %s "
            "ORDER BY skill_id DESC LIMIT 1",
            [name, bundle_hash.strip()],
        )
        pinned_by = "bundle_hash"
    elif version:
        skill = db_one(
            auth.conn,
            f"SELECT {_SKILL_COLUMNS} FROM maludb_skill WHERE skill_name = %s AND version = %s "
            "ORDER BY skill_id DESC LIMIT 1",
            [name, version.strip()],
        )
        pinned_by = "version"
    else:
        skill = db_one(
            auth.conn,
            f"SELECT {_SKILL_COLUMNS} FROM maludb_skill WHERE skill_name = %s "
            "AND enabled IS NOT FALSE ORDER BY skill_id DESC LIMIT 1",
            [name],
        )
        pinned_by = None
    if skill is None:
        json_error("not_found", "No skill by that name" + (f" and {pinned_by}." if pinned_by else " is enabled."), 404)
    return {"skill": _shape(skill), "pinned_by": pinned_by}


def _require_skill(auth, skill_id: int) -> dict:
    skill = db_one(
        auth.conn,
        "SELECT skill_id, skill_name, markdown, bundle_hash FROM maludb_skill WHERE skill_id = %s",
        [skill_id],
    )
    if skill is None:
        json_error("not_found", "Skill not found.", 404)
    return skill


@router.get("/v1/skills/{skill_id}/files")
def list_skill_files(skill_id: int, auth: Auth):
    skill = _require_skill(auth, skill_id)
    rows = db_query(
        auth.conn,
        """SELECT relative_path, file_hash, file_size, is_executable, media_type
             FROM maludb_skill_file WHERE skill_id = %s ORDER BY relative_path""",
        [skill_id],
    )
    for r in rows:
        r["file_size"], r["is_executable"] = int(r["file_size"]), bool(r["is_executable"])
    if not rows and skill.get("markdown"):  # a pre-bundle markdown skill is a one-file bundle
        rows = [
            {
                "relative_path": "SKILL.md",
                "file_hash": None,
                "file_size": len(str(skill["markdown"]).encode()),
                "is_executable": False,
                "media_type": "text/markdown",
            }
        ]
    return {"skill_id": skill_id, "name": skill["skill_name"], "bundle_hash": skill["bundle_hash"], "files": rows}


@router.get("/v1/skills/{skill_id}/files/{relative_path:path}")
def get_skill_file(skill_id: int, relative_path: str, auth: Auth):
    skill = _require_skill(auth, skill_id)
    if relative_path.startswith("/") or ".." in relative_path.split("/"):
        json_error("validation_failed", "The path must be relative and may not contain '..'.", 422)
    row = db_one(
        auth.conn,
        """SELECT f.relative_path, f.file_hash, f.file_size, f.is_executable, f.media_type,
                  sp.content_bytes, sp.content_text
             FROM maludb_skill_file f
             JOIN maludb_source_package sp ON sp.source_package_id = f.source_package_id
            WHERE f.skill_id = %s AND f.relative_path = %s""",
        [skill_id, relative_path],
    )
    if row is None:
        if relative_path == "SKILL.md" and skill.get("markdown"):
            content = str(skill["markdown"]).encode("utf-8")
            row = {
                "relative_path": "SKILL.md",
                "file_hash": None,
                "file_size": len(content),
                "is_executable": False,
                "media_type": "text/markdown",
            }
        else:
            json_error("not_found", "That file is not in the skill's bundle.", 404)
    else:
        content = (
            bytes(row.pop("content_bytes"))
            if row["content_bytes"] is not None
            else (row.get("content_text") or "").encode("utf-8")
        )
        row.pop("content_text", None)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    return {
        "skill_id": skill_id,
        "file": {
            **row,
            "file_size": int(row["file_size"]),
            "is_executable": bool(row["is_executable"]),
            "text": text,
            "content_base64": base64.b64encode(content).decode("ascii"),
        },
    }
