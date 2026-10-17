"""
Agent-skill ingest helpers (maludb_core 0.97.0).

A Claude Agent Skill is a directory bundle: SKILL.md (YAML frontmatter +
markdown body) plus optional scripts/, references/, assets/.  The terminal
parses the frontmatter and uploads the bundle; this module owns the parts
the server is responsible for:

  * the canonical bundle hash (identity of a skill version)
  * the deterministic materiality screens (does a revision supersede its
    parent or coexist with it?)
  * extraction of discovery subjects/verbs/keywords -- via the configured
    LLM when a model is given, or a deterministic fallback that needs no
    credentials (the "stub extractor" path).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# Frontmatter keys whose change always makes a revision materially
# different: they alter what the skill does or is allowed to do.
_MATERIAL_FRONTMATTER_KEYS = (
    "description",
    "when_to_use",
    "allowed-tools",
    "disallowed-tools",
    "compatibility",
)


# ---------------------------------------------------------------------------
# Canonical bundle hash
# ---------------------------------------------------------------------------


def file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def bundle_hash(files: list[dict[str, Any]]) -> str:
    """sha256 over the sorted per-file hashes.

    Canonical line format: "<file sha256>  <relative_path>\\n", sorted by
    relative_path.  A script edit changes the bundle hash even when SKILL.md
    is untouched.  The terminal computes the same value client-side; the
    server's recomputation is authoritative.
    """
    lines = sorted(f"{f['file_hash']}  {f['relative_path']}\n" for f in files)
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Materiality screens
# ---------------------------------------------------------------------------


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def materiality_screens(
    parent: dict[str, Any],
    new_markdown: str,
    new_frontmatter: dict[str, Any],
    new_files: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministic comparison of a revision against its parent skill row.

    Returns {"verdict": "material" | "non_material" | "gray", "reasons": [...]}.

      material      -- capability surface changed (description / tool policy /
                       any non-SKILL.md file): versions must coexist.
      non_material  -- bundles differ only in SKILL.md whitespace: supersede.
      gray          -- SKILL.md body text changed but nothing else did; a
                       judgment call (LLM judge when available, else treated
                       as material so nothing is hidden wrongly).

    parent carries the maludb_skill row (markdown, frontmatter_jsonb) plus a
    "files" list of {relative_path, file_hash} from malu$skill_file.
    """
    reasons: list[str] = []

    old_fm = parent.get("frontmatter_jsonb") or {}
    if isinstance(old_fm, str):
        try:
            old_fm = json.loads(old_fm)
        except (json.JSONDecodeError, ValueError):
            old_fm = {}

    for key in _MATERIAL_FRONTMATTER_KEYS:
        if (old_fm.get(key) or None) != ((new_frontmatter or {}).get(key) or None):
            reasons.append(f"frontmatter:{key}")

    old_files = {
        f["relative_path"]: f["file_hash"] for f in (parent.get("files") or []) if f.get("relative_path") != "SKILL.md"
    }
    new_files_map = {
        f["relative_path"]: f["file_hash"] for f in (new_files or []) if f.get("relative_path") != "SKILL.md"
    }
    for path in sorted(set(old_files) | set(new_files_map)):
        if old_files.get(path) != new_files_map.get(path):
            reasons.append(f"file:{path}")

    if reasons:
        return {"verdict": "material", "reasons": reasons}

    if _normalize_ws(parent.get("markdown") or "") == _normalize_ws(new_markdown):
        return {"verdict": "non_material", "reasons": ["skill_md_whitespace_only"]}

    return {"verdict": "gray", "reasons": ["skill_md_body_changed"]}


# ---------------------------------------------------------------------------
# Deterministic (no-LLM) discovery extraction
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    "a an and are as at be by for from in into is it of on or the this to use "
    "used uses using when with you your".split()
)


def deterministic_discovery(name: str, frontmatter: dict[str, Any]) -> dict[str, Any]:
    """Frontmatter-only discovery tags -- the credential-free fallback.

    The skill name and the description's content words become keywords; the
    skill itself is the only subject.  No verbs are guessed: a wrong verb tag
    poisons verb search, while keywords degrade gracefully.
    """
    keywords: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[^a-z0-9]+", name.lower()):
        if token and token not in _STOPWORDS and token not in seen:
            seen.add(token)
            keywords.append(token)
    description = str((frontmatter or {}).get("description") or "")
    for token in re.split(r"[^a-z0-9]+", description.lower()):
        if len(token) > 2 and token not in _STOPWORDS and token not in seen:
            seen.add(token)
            keywords.append(token)
    return {
        "keywords": keywords[:24],
        "subjects": [{"name": name}],
        "verbs": [],
    }


# ---------------------------------------------------------------------------
# Skill extraction JSON post-processing
# ---------------------------------------------------------------------------


def coerce_skill_extraction(
    extraction: dict[str, Any],
    name: str,
    markdown: str,
    frontmatter: dict[str, Any],
) -> dict[str, Any]:
    """Make an LLM extraction safe for the one-call ingest.

    Guarantees the document section (SKILL.md as an agent_skill document) and
    a subject of type 'skill' carrying the skill's own name, whatever the
    model produced.  The model's "keywords" key is left in place: ingest
    ignores unknown sections and the register step reads it.
    """
    out = dict(extraction or {})
    out["document"] = {
        "title": name,
        "content_text": markdown,
        "source_type": "document",
        "document_type": "agent_skill",
        "metadata": {"frontmatter": frontmatter or {}},
    }

    subjects = [s for s in out.get("subjects") or [] if isinstance(s, dict)]
    skill_key = None
    for s in subjects:
        if str(s.get("name", "")).strip().lower() == name.strip().lower():
            s["type"] = "skill"
            skill_key = s.get("key")
            break
    if skill_key is None:
        skill_key = "skill_self"
        subjects.insert(
            0,
            {
                "key": skill_key,
                "name": name,
                "type": "skill",
                "description": str((frontmatter or {}).get("description") or "") or None,
            },
        )
    out["subjects"] = subjects
    return out


# ---------------------------------------------------------------------------
# Reindex apply params
# ---------------------------------------------------------------------------


def build_reindex_params(
    extraction: dict[str, Any],
    subject_id_map: dict[str, int],
) -> dict[str, Any]:
    """Shape a (re-)extraction into the args maludb_skill_reindex_apply wants.

    Produces deduped, trimmed {subjects, verbs, keywords} from an extraction
    dict (the same shape coerce_skill_extraction yields).  ``subject_id_map``
    maps ``lower(name) -> subject_id`` for names that already exist in the
    tenant's registry; a matched subject carries its graph id so the rewritten
    tag keeps its FK link (find_skill matches on name regardless, but the id
    preserves the graph edge a name-only rewrite would drop).  Dedup is
    case-insensitive and first-wins, so the id-bearing form is kept.
    """
    subjects: list[dict[str, Any]] = []
    seen_subj: set[str] = set()
    for s in extraction.get("subjects") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip()
        if not name or name.lower() in seen_subj:
            continue
        seen_subj.add(name.lower())
        entry: dict[str, Any] = {"name": name}
        sid = subject_id_map.get(name.lower())
        if sid is not None:
            entry["id"] = sid
        subjects.append(entry)

    verbs: list[dict[str, Any]] = []
    seen_verb: set[str] = set()
    for v in extraction.get("verbs") or []:
        if not isinstance(v, dict):
            continue
        name = str(v.get("name") or "").strip()
        if name and name.lower() not in seen_verb:
            seen_verb.add(name.lower())
            verbs.append({"name": name})

    keywords: list[str] = []
    seen_kw: set[str] = set()
    for k in extraction.get("keywords") or []:
        kw = str(k).strip()
        if kw and kw.lower() not in seen_kw:
            seen_kw.add(kw.lower())
            keywords.append(kw)

    return {"subjects": subjects, "verbs": verbs, "keywords": keywords}
