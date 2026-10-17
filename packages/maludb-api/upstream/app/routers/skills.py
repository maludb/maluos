"""
Skill endpoints — list, create, detail, update, delete, duplicate (fork),
agent-skill ingest (0.97.0), and bundle download.

Ports PHP's skills.php, skills_id.php, skills_id_duplicate.php.

Live-schema mapping (DB column -> API field):
    skill_id   -> id
    skill_name -> name
Source table: maludb_skill (skill_id from sequence).
Defaults: version '1.0.0', visibility 'private', packaging_kind 'system_prompt', enabled true.
DB enforces visibility/packaging_kind value sets (-> 422).

Agent skills (maludb_core 0.97.0): POST /v1/skills/ingest registers a Claude
Agent Skill bundle (SKILL.md + scripts/references/assets) as an immutable
skill version — discovery tags extracted via the configured LLM (or a
deterministic frontmatter-only fallback), divergent fork lineage, and
supersession when a revision is not materially different from its parent.
Registered agent skills (bundle_hash set) are content-immutable: PATCH
rejects content fields with 409; lifecycle fields stay editable.

Retrieval mirrors the DB's two entry points:
    GET /v1/skills?q=…&subject=…&verb=…  -> maludb_skill_search/find_skill,
        ranked with score + match_reasons (subject/verb/keyword/text hits).
    GET /v1/skills/{id}/discovery        -> maludb_skill_get/get_skill, the
        full graph-tag payload (keywords, subjects, verbs, states, access).
"""

from __future__ import annotations

import base64
import binascii
import json

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from app.auth import Auth, get_auth_store
from app.database import db_exec, db_one, db_query, db_tx_core
from app.errors import json_error
from app.helpers.llm import llm_complete, llm_json_from_text
from app.helpers.llm_resolve import resolve_task_config
from app.helpers.query import Col, QuerySpec, build_where, content_range, parse_query, resolve_total, wants_count
from app.helpers.skills import (
    build_reindex_params,
    bundle_hash,
    coerce_skill_extraction,
    deterministic_discovery,
    file_sha256,
    materiality_screens,
)

router = APIRouter()

# Bundle size caps (the Anthropic API caps skill uploads at 30 MB zipped;
# we cap the unpacked JSON payload in the same spirit).
_MAX_FILE_BYTES = 5 * 1024 * 1024
_MAX_BUNDLE_BYTES = 30 * 1024 * 1024

# Content columns rejected on PATCH once a skill carries a bundle_hash.
_IMMUTABLE_FIELDS = ("name", "markdown", "version", "packaging_kind")

# Query spec — allowlist for the PostgREST-style grammar on the plain browse
# list of GET /v1/skills (the tag-search branch below is unaffected). Legacy
# ?visibility= (exact) and ?q= (substring) stay as reserved filters.
SKILL_QUERY = QuerySpec(
    columns={
        "id": Col("skill_id", int),
        "name": Col("skill_name", str),
        "description": Col("description", str),
        "version": Col("version", str),
        "visibility": Col("visibility", str),
        "packaging_kind": Col("packaging_kind", str),
        "enabled": Col("enabled", bool),
        "created_at": Col("created_at", str),
    },
    default_order=[("name", "asc")],
    default_limit=50,
    max_limit=200,
)


# ---------------------------------------------------------------------------
# Helper — load a single skill
# ---------------------------------------------------------------------------


def _load_skill(auth: Auth, skill_id: int) -> dict | None:
    """Fetch a single skill, or None if not found."""
    skill = db_one(
        auth.conn,
        """SELECT skill_id AS id, skill_name AS name, description, markdown, version,
                  visibility, packaging_kind, enabled, created_at, updated_at
             FROM maludb_skill
            WHERE skill_id = %s""",
        [skill_id],
    )
    if skill is None:
        return None
    skill["id"] = int(skill["id"])
    skill["enabled"] = None if skill["enabled"] is None else bool(skill["enabled"])
    return skill


# ===========================================================================
# GET /v1/skills — list skills
# ===========================================================================


@router.get("/v1/skills")
def list_skills(auth: Auth, request: Request, response: Response):
    params = request.query_params
    q = params.get("q")
    subject = params.get("subject")
    verb = params.get("verb")
    visibility = params.get("visibility")

    # Tag-aware discovery: subject/verb hit the skill_subject/skill_verb tag
    # tables, and a plain `q` rides the keyword(+40)/full-text(+10) rails of
    # find_skill via maludb_skill_search, which also folds in visible public
    # skills, scoring, match_reasons, and lineage. Routing q through search
    # (not ILIKE) is what surfaces keyword-tag hits a name/description LIKE
    # would miss. The `visibility` filter is a browse concern the search
    # function doesn't take, so a visibility-filtered `q` stays on the ILIKE
    # list; the no-arg list keeps the original ILIKE semantics too.
    if subject or verb or (q and not visibility):
        # This discovery path can't offset-paginate; reject offset rather than
        # silently returning duplicate pages under an unchanged Content-Range.
        if params.get("offset") not in (None, "", "0"):
            json_error("bad_request", "offset is not supported with skill text/tag search; use limit only.", 400)
        raw_limit = params.get("limit")
        try:
            search_limit = int(raw_limit) if raw_limit not in (None, "") else 50
        except ValueError:
            json_error("validation_failed", "'limit' must be an integer.", 422)
        search_limit = max(0, min(search_limit, 200))
        rows = db_query(
            auth.conn,
            """SELECT owner_schema, skill_id AS id, skill_name AS name, description,
                      version, visibility, subjects, verbs, keywords, score,
                      match_reasons, is_public, is_forkable,
                      source_owner_schema, source_skill_id, updated_at
                 FROM maludb_skill_search(%s, %s, %s, NULL, %s)""",
            [q, subject, verb, search_limit],
        )
        for r in rows:
            r["id"] = int(r["id"])
            r["score"] = None if r["score"] is None else float(r["score"])
            if r["source_skill_id"] is not None:
                r["source_skill_id"] = int(r["source_skill_id"])
        # Discovery results aren't offset-paginated or countable; report an open range.
        response.headers["Content-Range"] = content_range(0, len(rows), None)
        return {"skills": rows}

    # Plain browse list — PostgREST-style grammar via the shared parser. ?visibility=
    # is an ordinary spec column now (bare value = exact-match, op grammar works);
    # ?q= stays a substring shortcut; subject/verb only affect branch routing above.
    qp = parse_query(params, SKILL_QUERY, reserved=("q", "subject", "verb"))
    where_params = list(qp.where_params)

    q_clause = ""
    if q:
        q_clause = "(skill_name ILIKE %s OR description ILIKE %s)"
        where_params += [f"%{q}%", f"%{q}%"]

    where_sql = build_where(qp.where_clause, q_clause)

    sql = f"""SELECT {qp.select_list}
                FROM maludb_skill
                {where_sql}
                {qp.order_sql}
                {qp.limit_sql}"""

    rows = db_query(auth.conn, sql, where_params + qp.limit_params)
    for r in rows:
        if r.get("id") is not None:
            r["id"] = int(r["id"])
        if "enabled" in r:
            r["enabled"] = None if r["enabled"] is None else bool(r["enabled"])

    total = resolve_total(auth.conn, wants_count(request), "maludb_skill", where_sql, where_params)
    response.headers["Content-Range"] = content_range(qp.offset, len(rows), total)

    return {"skills": rows}


# ===========================================================================
# POST /v1/skills — create a skill
# ===========================================================================


@router.post("/v1/skills")
async def create_skill(auth: Auth, request: Request):
    body = await request.json()

    name = (body.get("name") or "").strip() if isinstance(body.get("name"), str) else ""
    if not name:
        json_error("missing_field", 'Field "name" is required.', 400)

    cols = ["skill_name"]
    placeholders = ["%s"]
    params: list = [name]

    for f in ("description", "markdown", "version", "visibility", "packaging_kind"):
        if f in body and body[f] is not None:
            cols.append(f)
            placeholders.append("%s")
            params.append(str(body[f]))

    if "enabled" in body:
        cols.append("enabled")
        placeholders.append("%s")
        params.append("true" if body["enabled"] else "false")

    created = db_one(
        auth.conn,
        f"""INSERT INTO maludb_skill ({", ".join(cols)})
           VALUES ({", ".join(placeholders)})
           RETURNING skill_id AS id, skill_name AS name, description, markdown, version,
                     visibility, packaging_kind, enabled, created_at""",
        params,
    )
    created["id"] = int(created["id"])
    created["enabled"] = None if created["enabled"] is None else bool(created["enabled"])

    return JSONResponse(status_code=201, content={"skill": created})


# ===========================================================================
# GET /v1/skills/{id} — skill detail
# ===========================================================================


@router.get("/v1/skills/{skill_id}")
def get_skill(skill_id: int, auth: Auth):
    skill = _load_skill(auth, skill_id)
    if skill is None:
        json_error("not_found", "Skill not found.", 404)
    return {"skill": skill}


# ===========================================================================
# GET /v1/skills/{id}/discovery — full graph-tag payload (get_skill facade)
# ===========================================================================


@router.get("/v1/skills/{skill_id}/discovery")
def get_skill_discovery(skill_id: int, auth: Auth):
    """Full discovery payload via the maludb_skill_get / get_skill facade.

    Returns exactly the graph-tag view that find_skill scores against: the
    skill row plus its keywords, subject tags, verb tags, state machine, and
    access policy. This is how a caller confirms a saved skill is actually in
    the knowledge graph (subjects/verbs attached, +100/+80 facets live) rather
    than discoverable by full-text alone. The facade applies the same
    visibility gate as find_skill, so a not-visible skill reads as 404.
    """
    # The owner schema scopes the lookup; a tenant's own rows carry it, and
    # legacy rows (NULL) resolve to current_schema().
    src = db_one(
        auth.conn,
        "SELECT COALESCE(owner_schema, current_schema()) AS owner_schema  FROM maludb_skill WHERE skill_id = %s",
        [skill_id],
    )
    if src is None:
        json_error("not_found", "Skill not found.", 404)

    row = db_one(
        auth.conn,
        "SELECT payload FROM maludb_skill_get(%s, %s)",
        [src["owner_schema"], skill_id],
    )
    # get_skill emits no row when the skill isn't visible to this tenant.
    if row is None or row.get("payload") is None:
        json_error("not_found", "Skill not found or not visible.", 404)

    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return {"discovery": payload}


# ===========================================================================
# PATCH /v1/skills/{id} — update a skill
# ===========================================================================


@router.patch("/v1/skills/{skill_id}")
async def update_skill(skill_id: int, auth: Auth, request: Request):
    row = db_one(
        auth.conn,
        "SELECT bundle_hash FROM maludb_skill WHERE skill_id = %s",
        [skill_id],
    )
    if row is None:
        json_error("not_found", "Skill not found.", 404)

    body = await request.json()

    # Registered agent skills are content-immutable (a DB trigger enforces
    # this too); a changed bundle must be re-ingested as a new skill version.
    if row.get("bundle_hash"):
        blocked = [f for f in _IMMUTABLE_FIELDS if f in body]
        if blocked:
            json_error(
                "skill_content_immutable",
                "Fields "
                + ", ".join(blocked)
                + " are immutable on a registered agent skill; re-upload the changed bundle"
                " via POST /v1/skills/ingest (it becomes a new version with fork lineage)."
                " Editable here: description, visibility, enabled.",
                409,
            )
    fields: list[str] = []
    params: list = []

    if "name" in body:
        name = str(body["name"]).strip() if body["name"] is not None else ""
        if not name:
            json_error("validation_failed", 'Field "name" cannot be empty.', 422)
        fields.append("skill_name = %s")
        params.append(name)

    for f in ("description", "markdown", "version", "visibility", "packaging_kind"):
        if f in body:
            fields.append(f"{f} = %s")
            params.append(None if body[f] is None else str(body[f]))

    if "enabled" in body:
        fields.append("enabled = %s")
        params.append("true" if body["enabled"] else "false")

    if not fields:
        json_error(
            "bad_request",
            "No updatable fields provided (name, description, version, visibility, packaging_kind, enabled).",
            400,
        )

    fields.append("updated_at = now()")
    params.append(skill_id)
    db_exec(
        auth.conn,
        f"UPDATE maludb_skill SET {', '.join(fields)} WHERE skill_id = %s",
        params,
    )

    return {"skill": _load_skill(auth, skill_id)}


# ===========================================================================
# DELETE /v1/skills/{id} — delete a skill
# ===========================================================================


@router.delete("/v1/skills/{skill_id}")
def delete_skill(skill_id: int, auth: Auth):
    n = db_exec(auth.conn, "DELETE FROM maludb_skill WHERE skill_id = %s", [skill_id])
    if n == 0:
        json_error("not_found", "Skill not found.", 404)
    return {"deleted": True, "id": skill_id}


# ===========================================================================
# POST /v1/skills/{id}/duplicate — fork a skill
# ===========================================================================


@router.post("/v1/skills/{skill_id}/duplicate")
async def duplicate_skill(skill_id: int, auth: Auth, request: Request):
    src = db_one(
        auth.conn,
        """SELECT skill_id, skill_name, COALESCE(owner_schema, current_schema()) AS owner_schema
             FROM maludb_skill WHERE skill_id = %s""",
        [skill_id],
    )
    if src is None:
        json_error("not_found", "Skill not found.", 404)

    body = await request.json()
    new_name = str(body["name"]) if "name" in body and body["name"] is not None and str(body["name"]).strip() else None
    new_version = (
        str(body["version"])
        if "version" in body and body["version"] is not None and str(body["version"]).strip()
        else "1.0.0"
    )

    def do_fork(conn):  # noqa: ANN001, ANN202
        return db_one(
            conn,
            "SELECT maludb_skill_fork(%s, %s, %s, %s) AS id",
            [src["owner_schema"], skill_id, new_name, new_version],
        )

    row = db_tx_core(auth.conn, do_fork)

    new_id = int(row["id"])
    skill = db_one(
        auth.conn,
        """SELECT skill_id AS id, skill_name AS name, description, version,
                  visibility, packaging_kind, enabled, source_skill_id, created_at
             FROM maludb_skill WHERE skill_id = %s""",
        [new_id],
    )
    skill["id"] = int(skill["id"])
    skill["source_skill_id"] = None if skill["source_skill_id"] is None else int(skill["source_skill_id"])
    skill["enabled"] = None if skill["enabled"] is None else bool(skill["enabled"])

    return JSONResponse(status_code=201, content={"skill": skill})


# ===========================================================================
# POST /v1/skills/ingest — register a Claude Agent Skill bundle (0.97.0)
# ===========================================================================


def _decode_files(body: dict, name: str, markdown: str) -> list[dict]:
    """Decode the request's files[] into {relative_path, content(bytes), ...}.

    Accepts content_base64 (binary-safe) or content_text per file.  SKILL.md
    is synthesized from the markdown when the client didn't include it, so
    the manifest always describes the complete, reconstructable bundle.
    """
    raw = body.get("files") or []
    if not isinstance(raw, list):
        json_error("validation_failed", 'Field "files" must be an array.', 422)

    files: list[dict] = []
    total = 0
    seen_paths: set[str] = set()
    for i, f in enumerate(raw):
        if not isinstance(f, dict):
            json_error("validation_failed", f"files[{i}] must be an object.", 422)
        rel = str(f.get("relative_path") or "").strip()
        if not rel or rel.startswith("/") or ".." in rel.split("/"):
            json_error("validation_failed", f"files[{i}].relative_path is missing or unsafe.", 422)
        if rel in seen_paths:
            json_error("validation_failed", f"files[{i}]: duplicate relative_path {rel!r}.", 422)
        seen_paths.add(rel)

        if f.get("content_base64") is not None:
            try:
                content = base64.b64decode(str(f["content_base64"]), validate=True)
            except (binascii.Error, ValueError):
                json_error("validation_failed", f"files[{i}].content_base64 is not valid base64.", 422)
        elif f.get("content_text") is not None:
            content = str(f["content_text"]).encode("utf-8")
        else:
            json_error("validation_failed", f"files[{i}] needs content_base64 or content_text.", 422)

        if len(content) > _MAX_FILE_BYTES:
            json_error("payload_too_large", f"files[{i}] ({rel}) exceeds {_MAX_FILE_BYTES} bytes.", 413)
        total += len(content)
        if total > _MAX_BUNDLE_BYTES:
            json_error("payload_too_large", f"Bundle exceeds {_MAX_BUNDLE_BYTES} bytes.", 413)

        files.append(
            {
                "relative_path": rel,
                "content": content,
                "file_hash": file_sha256(content),
                "file_size": len(content),
                "is_executable": bool(f.get("is_executable")),
                "media_type": (str(f["media_type"]).strip() or None) if f.get("media_type") else None,
            }
        )

    if "SKILL.md" not in seen_paths:
        content = markdown.encode("utf-8")
        files.insert(
            0,
            {
                "relative_path": "SKILL.md",
                "content": content,
                "file_hash": file_sha256(content),
                "file_size": len(content),
                "is_executable": False,
                "media_type": "text/markdown",
            },
        )
    return files


def _render_type_catalog(auth: Auth) -> tuple[str, str]:
    """Entity-type and event-kind bullet lists from the live catalog (0.96.0)."""
    try:
        type_rows = db_query(
            auth.conn,
            "SELECT category, subject_type, description FROM maludb_subject_type ORDER BY category, sort_order",
        )
    except Exception:
        type_rows = db_query(
            auth.conn,
            "SELECT category, subject_type, description"
            " FROM maludb_core.malu$svpor_subject_type ORDER BY category, sort_order",
        )
    entity_lines: list[str] = []
    event_lines: list[str] = []
    for r in type_rows:
        desc = " — " + r["description"] if r.get("description") and str(r["description"]).strip() else ""
        line = f"  - {r['subject_type']}{desc}"
        (event_lines if (r.get("category") or "entity") == "event" else entity_lines).append(line)
    return (
        "\n".join(entity_lines) if entity_lines else "  - other",
        "\n".join(event_lines) if event_lines else "  - task",
    )


def _judge_materiality(pr: dict, parent_markdown: str, new_markdown: str, name: str) -> bool:
    """LLM judge for the gray zone: SKILL.md body changed, nothing else did.

    Returns True (materially different -> coexist) unless the model clearly
    answers otherwise; a judge failure must never hide a version wrongly.
    """
    system = (
        "You compare two versions of an AI agent skill (its SKILL.md instructions) and decide"
        " whether the revision MATERIALLY changes what the skill does: different capabilities,"
        " different behavior, different instructions an agent would follow. Typo fixes, rewording"
        " with identical meaning, and formatting changes are NOT material."
        ' Respond with exactly one JSON object: {"materially_different": true|false}.'
    )
    user = f"SKILL: {name}\n\n=== PARENT VERSION ===\n{parent_markdown}\n\n=== NEW VERSION ===\n{new_markdown}\n"
    cfg = {
        "api_format": pr.get("api_format", "openai"),
        "base_url": pr.get("base_url", ""),
        "model_identifier": pr.get("model_identifier"),
        "token": pr["api_key"],
        "max_tokens": 64,
        "generation_params": json.loads(pr["generation_params"]) if pr.get("generation_params") else {},
    }
    try:
        verdict = llm_json_from_text(llm_complete(cfg, system, user))
    except Exception:
        return True
    if isinstance(verdict, dict) and isinstance(verdict.get("materially_different"), bool):
        return verdict["materially_different"]
    return True


@router.post("/v1/skills/ingest")
async def ingest_skill(auth: Auth, request: Request):
    body = await request.json()

    name = (body.get("name") or "").strip() if isinstance(body.get("name"), str) else ""
    markdown = str(body.get("markdown") or "")
    if not name:
        json_error("missing_field", 'Field "name" is required.', 400)
    if not markdown.strip():
        json_error("missing_field", 'Field "markdown" (the SKILL.md text) is required.', 400)

    frontmatter = body.get("frontmatter") if isinstance(body.get("frontmatter"), dict) else {}
    model = str(body["model"]).strip() if body.get("model") else None
    preview = bool(body.get("preview"))

    files = _decode_files(body, name, markdown)
    computed_hash = bundle_hash(files)

    # maludb_skill_register arrived in 0.97.0 (with the bundle schema).
    has_register = db_one(
        auth.conn,
        "SELECT EXISTS(SELECT 1 FROM pg_proc WHERE proname = 'maludb_skill_register') AS ok",
    )
    if not has_register or not has_register["ok"]:
        json_error(
            "ingest_unavailable",
            "maludb_skill_register is not available (requires maludb_core 0.97.0;"
            " re-run enable_memory_schema('<tenant>') after upgrading).",
            501,
        )

    # Idempotent re-push: same name + bundle -> the existing version, no LLM.
    existing = db_one(
        auth.conn,
        "SELECT skill_id AS id, version FROM maludb_skill WHERE skill_name = %s AND bundle_hash = %s",
        [name, computed_hash],
    )
    if existing and not preview:
        return {
            "skill_id": int(existing["id"]),
            "version": existing["version"],
            "bundle_hash": computed_hash,
            "reused": True,
        }

    # Parent: explicit {owner_schema, skill_id}, else the newest enabled
    # same-name skill in the tenant's own schema (the re-upload case).
    parent_schema = None
    parent_id = None
    parent_note = None
    parent_body = body.get("parent")
    if isinstance(parent_body, dict) and parent_body.get("skill_id") is not None:
        parent_schema = str(parent_body.get("owner_schema") or "").strip() or None
        parent_id = int(parent_body["skill_id"])
        if parent_schema is None:
            json_error("validation_failed", 'Field "parent.owner_schema" is required with parent.skill_id.', 422)
    else:
        auto = db_one(
            auth.conn,
            """SELECT skill_id AS id, owner_schema FROM maludb_skill
                WHERE skill_name = %s AND enabled ORDER BY skill_id DESC LIMIT 1""",
            [name],
        )
        if auto:
            parent_schema = auto["owner_schema"]
            parent_id = int(auto["id"])
            parent_note = "auto_detected_same_name"

    # Materiality: explicit override > deterministic screens > LLM judge.
    materiality: dict = {"verdict": "material", "reasons": ["no_parent"]}
    materially_different = True

    # `enabled` has always been an argument of maludb_skill_register; the route never passed it, so a
    # host ingesting a proposal had it live until its follow-up PATCH. `review_state: "proposed"`
    # (maludb_core 0.106.0) keeps it out of every resolve until someone approves it.
    enabled = body.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        json_error("invalid_field", "enabled must be true or false.", 422)
    enabled = True if enabled is None else enabled
    review_state = body.get("review_state")
    if review_state not in (None, "approved", "proposed"):
        json_error("invalid_field", "review_state must be approved or proposed.", 422)
    proposed_by = str(body.get("proposed_by") or "").strip() or None
    if review_state == "proposed":
        has_review = db_one(
            auth.conn,
            "SELECT to_regprocedure(quote_ident(current_schema())"
            " || '.maludb_skill_review(bigint,text,text,text)') IS NOT NULL AS ok",
        )
        if not has_review or not has_review["ok"]:
            json_error(
                "ingest_unavailable",
                "review_state needs maludb_core 0.106.0 (re-run enable_memory_schema('<tenant>') after upgrading).",
                501,
            )
    if parent_id is not None:
        parent_row = db_one(
            auth.conn,
            """SELECT s.markdown, s.frontmatter_jsonb,
                      COALESCE((SELECT jsonb_agg(jsonb_build_object(
                                    'relative_path', f.relative_path,
                                    'file_hash', f.file_hash))
                                  FROM maludb_core.malu$skill_file f
                                 WHERE f.owner_schema = s.owner_schema
                                   AND f.skill_id = s.skill_id), '[]'::jsonb) AS files
                 FROM maludb_core.malu$skill_package s
                WHERE s.owner_schema = %s AND s.skill_id = %s""",
            [parent_schema, parent_id],
        )
        if parent_row is None:
            json_error("not_found", "Parent skill not found.", 404)
        parent_files = parent_row["files"]
        if isinstance(parent_files, str):
            parent_files = json.loads(parent_files)
        materiality = materiality_screens(
            {
                "markdown": parent_row["markdown"],
                "frontmatter_jsonb": parent_row["frontmatter_jsonb"],
                "files": parent_files,
            },
            markdown,
            frontmatter,
            files,
        )
        if isinstance(body.get("materially_different"), bool):
            materially_different = body["materially_different"]
            materiality["reasons"].append("caller_override")
        elif materiality["verdict"] == "material":
            materially_different = True
        elif materiality["verdict"] == "non_material":
            materially_different = False
        else:  # gray zone
            pr_judge = resolve_task_config(get_auth_store(), auth.user_id, "skill_extract", model)
            if pr_judge and pr_judge.get("api_key"):
                materially_different = _judge_materiality(pr_judge, parent_row["markdown"] or "", markdown, name)
                materiality["reasons"].append("llm_judged")
            else:
                materially_different = True
                materiality["reasons"].append("gray_zone_default_material")
        materiality["materially_different"] = materially_different

    # Discovery extraction: LLM when a model is configured (explicit `model`,
    # or the user's stored 'skill_extract' choice), else the deterministic
    # frontmatter-only fallback.
    extraction = None
    discovery = None
    store = get_auth_store()
    pr = resolve_task_config(store, auth.user_id, "skill_extract", model)
    if model and pr is None:
        json_error(
            "model_not_configured",
            f'No prompt configured for model "{model}". Set one via POST /v1/model-prompts.',
            422,
        )
    if pr is not None:
        model = pr.get("model_name") or model
        entity_block, event_block = _render_type_catalog(auth)
        system = (
            str(pr.get("system_prompt", ""))
            .replace("{{ENTITY_TYPES}}", entity_block)
            .replace("{{EVENT_KINDS}}", event_block)
        )
        user_msg = (
            f"SKILL_NAME: {name}\n\nFRONTMATTER:\n{json.dumps(frontmatter, ensure_ascii=False)}\n\n"
            f"SKILL_MD:\n{markdown}\n"
        )
        if preview:
            return {
                "model": model,
                "system_prompt": system,
                "user_message": user_msg,
                "bundle_hash": computed_hash,
                "materiality": materiality,
                "parent": {"owner_schema": parent_schema, "skill_id": parent_id, "note": parent_note},
            }
        if not pr.get("api_key"):
            if pr.get("source") in ("catalog_explicit", "user_choice"):
                msg = (
                    f'No API key stored for provider "{pr.get("provider")}".'
                    f" Set one via PUT /v1/llm/providers/{pr.get('provider')}."
                )
            else:
                msg = f'No API key set for model "{model}".'
            json_error("model_api_key_missing", msg, 409)
        cfg = {
            "api_format": pr.get("api_format", "openai"),
            "base_url": pr.get("base_url", ""),
            "model_identifier": pr.get("model_identifier") or model,
            "token": pr["api_key"],
            "max_tokens": int(pr.get("max_tokens", 2048)),
            "generation_params": json.loads(pr["generation_params"]) if pr.get("generation_params") else {},
        }
        extraction = llm_json_from_text(llm_complete(cfg, system, user_msg))
        if extraction is None:
            json_error("upstream_error", "LLM output was not a JSON object.", 502)
        extraction = coerce_skill_extraction(extraction, name, markdown, frontmatter)
    else:
        discovery = deterministic_discovery(name, frontmatter)
        extraction = coerce_skill_extraction(
            {"subjects": [], "verbs": [], "edges": [], "keywords": discovery["keywords"]},
            name,
            markdown,
            frontmatter,
        )
        if preview:
            return {
                "model": None,
                "extraction": extraction,
                "bundle_hash": computed_hash,
                "materiality": materiality,
                "parent": {"owner_schema": parent_schema, "skill_id": parent_id, "note": parent_note},
            }

    version = (
        str(body["version"]).strip()
        if body.get("version")
        else (
            str((frontmatter.get("metadata") or {}).get("version") or "").strip() or None
            if isinstance(frontmatter.get("metadata"), dict)
            else None
        )
    )
    description = str(frontmatter.get("description") or "").strip() or None

    # One transaction: graph ingest, bundle storage, skill registration.
    def _ingest(conn):
        ingest_row = db_one(
            conn,
            """SELECT maludb_memory_ingest_extraction(
                        p_extraction => %s::jsonb, p_source_kind => 'document',
                        p_source_id => NULL, p_provenance => 'suggested') AS result""",
            [json.dumps(extraction)],
        )
        report = ingest_row["result"]
        if isinstance(report, str):
            report = json.loads(report)

        # subject names -> graph ids, via the report's key->id map
        ids = report.get("ids") or {}
        subjects_param = []
        for s in extraction.get("subjects") or []:
            entry = {"name": s.get("name")}
            key = s.get("key")
            if key is not None and str(key) in ids:
                entry["id"] = ids[str(key)]
            subjects_param.append(entry)
        verbs_param = [{"name": v.get("name")} for v in extraction.get("verbs") or [] if v.get("name")]
        keywords = [str(k) for k in extraction.get("keywords") or [] if str(k).strip()]

        # Bundle files: content-hash-deduped source packages in the tenant schema.
        files_param = []
        for f in files:
            sp = db_one(
                conn,
                """SELECT source_package_id FROM maludb_source_package
                    WHERE content_hash = %s AND source_type = 'skill_file'
                    ORDER BY source_package_id LIMIT 1""",
                [f["file_hash"]],
            )
            if sp is None:
                sp = db_one(
                    conn,
                    """INSERT INTO maludb_source_package
                           (source_type, content_bytes, media_type, content_size, content_hash, ingested_at)
                       VALUES ('skill_file', %s, %s, %s, %s, now())
                       RETURNING source_package_id""",
                    [f["content"], f["media_type"], f["file_size"], f["file_hash"]],
                )
            files_param.append(
                {
                    "relative_path": f["relative_path"],
                    "source_package_id": int(sp["source_package_id"]),
                    "file_hash": f["file_hash"],
                    "file_size": f["file_size"],
                    "is_executable": f["is_executable"],
                    "media_type": f["media_type"],
                }
            )

        reg_row = db_one(
            conn,
            """SELECT maludb_skill_register(
                        p_skill_name => %s, p_markdown => %s, p_bundle_hash => %s,
                        p_description => %s, p_frontmatter => %s::jsonb, p_version => %s,
                        p_keywords => %s, p_subjects => %s::jsonb, p_verbs => %s::jsonb,
                        p_files => %s::jsonb, p_parent_owner_schema => %s,
                        p_parent_skill_id => %s, p_materially_different => %s,
                        p_enabled => %s) AS result""",
            [
                name,
                markdown,
                computed_hash,
                description,
                json.dumps(frontmatter),
                version,
                keywords or None,
                json.dumps(subjects_param),
                json.dumps(verbs_param),
                json.dumps(files_param),
                parent_schema,
                parent_id,
                materially_different,
                enabled,
            ],
        )
        register = reg_row["result"]
        if isinstance(register, str):
            register = json.loads(register)
        if review_state == "proposed" and register.get("skill_id") is not None:
            # 0.106.0: review is apart from `enabled`. Same transaction as the register, so the skill
            # never exists unreviewed -- the window a host used to close with a PATCH after the fact.
            review = db_one(
                conn,
                "SELECT maludb_skill_review(%s, 'proposed', %s) AS r",
                [int(register["skill_id"]), proposed_by],
            )
            register["review"] = review["r"] if not isinstance(review["r"], str) else json.loads(review["r"])
        return {"ingest": report, "register": register}

    result = db_tx_core(auth.conn, _ingest)

    return JSONResponse(
        status_code=201,
        content={
            "skill_id": result["register"].get("skill_id"),
            "version": result["register"].get("version"),
            "bundle_hash": computed_hash,
            "reused": bool(result["register"].get("reused")),
            "model": model,
            "parent": {"owner_schema": parent_schema, "skill_id": parent_id, "note": parent_note},
            "materiality": materiality,
            "register": result["register"],
            "ingest": result["ingest"],
        },
    )


# ===========================================================================
# POST /v1/skills/reindex/run — background reindex sweep (one batch) (0.99.0)
# ===========================================================================


def _reindex_extract_tags(auth: Auth, name: str, markdown: str, frontmatter: dict, pr: dict | None) -> tuple[dict, str]:
    """Re-derive discovery tags for one skill. Returns (extraction, used_model).

    Mirrors the ingest extraction (same skill_extract prompt, same deterministic
    fallback) but stays read-only w.r.t. the graph: the caller feeds the result
    to maludb_skill_reindex_apply, which rewrites the skill's 'extracted' tags.
    coerce_skill_extraction is reused for its 'skill'-subject guarantee; the
    document section it adds is ignored — reindex never re-mints the SKILL.md
    document. A model that returns no JSON object degrades to the deterministic
    path so one bad skill never stalls the sweep.
    """
    if pr is not None and pr.get("api_key"):
        entity_block, event_block = _render_type_catalog(auth)
        system = (
            str(pr.get("system_prompt", ""))
            .replace("{{ENTITY_TYPES}}", entity_block)
            .replace("{{EVENT_KINDS}}", event_block)
        )
        user_msg = (
            f"SKILL_NAME: {name}\n\nFRONTMATTER:\n"
            f"{json.dumps(frontmatter, ensure_ascii=False)}\n\nSKILL_MD:\n{markdown}\n"
        )
        cfg = {
            "api_format": pr.get("api_format", "openai"),
            "base_url": pr.get("base_url", ""),
            "model_identifier": pr.get("model_identifier") or pr.get("model_name"),
            "token": pr["api_key"],
            "max_tokens": int(pr.get("max_tokens", 2048)),
            "generation_params": json.loads(pr["generation_params"]) if pr.get("generation_params") else {},
        }
        extraction = llm_json_from_text(llm_complete(cfg, system, user_msg))
        if extraction is not None:
            return (
                coerce_skill_extraction(extraction, name, markdown, frontmatter),
                pr.get("model_name") or "llm",
            )
    discovery = deterministic_discovery(name, frontmatter)
    extraction = coerce_skill_extraction(
        {"subjects": [], "verbs": [], "edges": [], "keywords": discovery["keywords"]},
        name,
        markdown,
        frontmatter,
    )
    return extraction, "deterministic"


def _resolve_subject_ids(auth: Auth, names: list[str]) -> dict[str, int]:
    """Map lower(canonical_name) -> subject_id for names already in the tenant
    registry (one batched, read-only lookup). Unknown names stay name-only."""
    uniq = sorted({n.lower() for n in names if n and n.strip()})
    if not uniq:
        return {}
    rows = db_query(
        auth.conn,
        "SELECT lower(canonical_name) AS k, subject_id AS id"
        "  FROM maludb_subject WHERE lower(canonical_name) = ANY(%s)",
        [uniq],
    )
    return {r["k"]: int(r["id"]) for r in rows if r.get("id") is not None}


@router.post("/v1/skills/reindex/run")
def reindex_skills_run(
    auth: Auth,
    limit: int = Query(default=32, le=200),
    max_age: str | None = Query(default="30 days", max_length=64),
):
    """Run one skill-reindex sweep batch for the calling tenant (maludb_core 0.99.0).

    The cron-driven half of the background reindex (DB contract in maludb_core's
    docs/skill-reindex.md). Claims the stalest skills — never indexed, older than
    `max_age`, or older than the registry watermark — re-derives their discovery
    tags against the *current* knowledge graph via the user's `skill_extract`
    model (or the deterministic fallback), and applies a replace-`extracted`
    rewrite through maludb_skill_reindex_apply. Curator `manual` tags are
    preserved by the DB. Intended to be invoked on a schedule by an external
    cron / systemd timer; also safe to call on demand. One skill's failure is
    captured in `errors` and does not abort the batch.
    """
    # The reindex facades arrived in 0.99.0.
    has_claim = db_one(
        auth.conn,
        "SELECT EXISTS(SELECT 1 FROM pg_proc WHERE proname = 'maludb_skill_reindex_claim') AS ok",
    )
    if not has_claim or not has_claim["ok"]:
        json_error(
            "reindex_unavailable",
            "maludb_skill_reindex_claim is not available (requires maludb_core 0.99.0;"
            " re-run enable_memory_schema('<tenant>') after upgrading).",
            501,
        )

    age = (max_age or "").strip() or None
    rows = db_query(
        auth.conn,
        "SELECT skill_id, skill_name, markdown, frontmatter_jsonb"
        "  FROM maludb_skill_reindex_claim(%s, %s::interval, %s)",
        [limit, age, True],
    )

    store = get_auth_store()
    pr = resolve_task_config(store, auth.user_id, "skill_extract", None)

    reindexed: list[dict] = []
    errors: list[dict] = []
    for r in rows:
        sid = int(r["skill_id"])
        name = r["skill_name"]
        markdown = r["markdown"] or ""
        fm = r["frontmatter_jsonb"] or {}
        if isinstance(fm, str):
            try:
                fm = json.loads(fm)
            except (json.JSONDecodeError, ValueError):
                fm = {}
        try:
            extraction, used_model = _reindex_extract_tags(auth, name, markdown, fm, pr)
            names = [str(s.get("name") or "") for s in (extraction.get("subjects") or []) if isinstance(s, dict)]
            id_map = _resolve_subject_ids(auth, names)
            params = build_reindex_params(extraction, id_map)

            def _apply(conn, _sid=sid, _p=params, _m=used_model):  # noqa: ANN001, ANN202
                return db_one(
                    conn,
                    "SELECT maludb_skill_reindex_apply("
                    "  p_skill_id => %s, p_subjects => %s::jsonb, p_verbs => %s::jsonb,"
                    "  p_keywords => %s, p_model => %s) AS result",
                    [_sid, json.dumps(_p["subjects"]), json.dumps(_p["verbs"]), _p["keywords"] or None, _m],
                )

            applied = db_tx_core(auth.conn, _apply)["result"]
            if isinstance(applied, str):
                applied = json.loads(applied)
            reindexed.append({"skill_id": sid, "name": name, "model": used_model, "applied": applied})
        except Exception as exc:  # one skill's failure must not abort the sweep
            errors.append({"skill_id": sid, "name": name, "error": str(exc)})

    return {
        "claimed": len(rows),
        "reindexed": reindexed,
        "errors": errors,
        "model": (pr.get("model_name") if pr else None),
        "limit": limit,
        "max_age": age,
    }


# ===========================================================================
# GET /v1/skills/{id}/bundle — full bundle for reconstruction (skill pull)
# ===========================================================================


@router.get("/v1/skills/{skill_id}/bundle")
def get_skill_bundle(skill_id: int, auth: Auth):
    skill = db_one(
        auth.conn,
        """SELECT skill_id AS id, skill_name AS name, description, markdown, version,
                  visibility, enabled, bundle_hash, frontmatter_jsonb,
                  source_owner_schema, source_skill_id, created_at
             FROM maludb_skill WHERE skill_id = %s""",
        [skill_id],
    )
    if skill is None:
        json_error("not_found", "Skill not found.", 404)
    skill["id"] = int(skill["id"])
    if skill["source_skill_id"] is not None:
        skill["source_skill_id"] = int(skill["source_skill_id"])
    skill["enabled"] = None if skill["enabled"] is None else bool(skill["enabled"])

    rows = db_query(
        auth.conn,
        """SELECT f.relative_path, f.file_hash, f.file_size, f.is_executable,
                  f.media_type, sp.content_bytes, sp.content_text
             FROM maludb_skill_file f
             JOIN maludb_source_package sp ON sp.source_package_id = f.source_package_id
            WHERE f.skill_id = %s
            ORDER BY f.relative_path""",
        [skill_id],
    )
    files = []
    for r in rows:
        content = (
            bytes(r["content_bytes"]) if r["content_bytes"] is not None else (r["content_text"] or "").encode("utf-8")
        )
        files.append(
            {
                "relative_path": r["relative_path"],
                "file_hash": r["file_hash"],
                "file_size": int(r["file_size"]),
                "is_executable": bool(r["is_executable"]),
                "media_type": r["media_type"],
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )

    # Older (pre-bundle) markdown skills still pull as a one-file bundle.
    if not files and skill.get("markdown"):
        content = str(skill["markdown"]).encode("utf-8")
        files.append(
            {
                "relative_path": "SKILL.md",
                "file_hash": file_sha256(content),
                "file_size": len(content),
                "is_executable": False,
                "media_type": "text/markdown",
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )

    return {"skill": skill, "files": files}
