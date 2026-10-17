"""
LLM configuration endpoints — seeded catalog, per-user provider keys, and
per-user task -> model choices.

    GET    /v1/llm/catalog              — seeded models × tasks (+ caller's key/choice state)
    GET    /v1/llm/providers            — caller's providers (key value never returned)
    PUT    /v1/llm/providers/{provider} — store/update the caller's provider API key
    DELETE /v1/llm/providers/{provider} — remove the caller's provider API key
    GET    /v1/llm/models               — effective task -> model choices
    PUT    /v1/llm/models/{task}        — choose a model for a task
    DELETE /v1/llm/models/{task}        — revert a task to the server default

All endpoints are Bearer-authenticated (unlike the legacy /v1/model-prompts,
which requires raw Postgres credentials).  Config is keyed by the token's
user_id, so every token a user holds shares the same keys and choices.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.auth import Auth, get_auth_store
from app.errors import json_error

router = APIRouter()

# The task every legacy deployment implicitly has: /v1/memory/ingest defaults
# to the 'chatgpt-4o' model_prompts row when no choice is set.
_LEGACY_EXTRACT_DEFAULT = "chatgpt-4o"


# ---------------------------------------------------------------------------
# GET /v1/llm/catalog — seeded models × tasks
# ---------------------------------------------------------------------------


@router.get("/v1/llm/catalog")
def llm_catalog(auth: Auth):
    store = get_auth_store()
    keys = {k["provider"] for k in store.list_user_provider_keys(auth.user_id) if k["key_set"]}
    choices = {c["task"]: c["model_name"] for c in store.list_user_model_choices(auth.user_id)}

    models = []
    for r in store.list_default_prompts():
        models.append(
            {
                "provider": r["provider"],
                "model_name": r["model_name"],
                "model_identifier": r["model_identifier"],
                "api_format": r["api_format"],
                "base_url": r["base_url"],
                "task": r["task"],
                "max_tokens": int(r["max_tokens"]),
                "has_system_prompt": bool(r["has_system_prompt"]),
                "key_set": r["provider"] in keys,
                "is_choice": choices.get(r["task"]) == r["model_name"],
            }
        )
    return {"tasks": store.catalog_tasks(), "models": models}


# ---------------------------------------------------------------------------
# GET /v1/llm/providers — caller's stored keys (key_set only, never the key)
# ---------------------------------------------------------------------------


@router.get("/v1/llm/providers")
def list_providers(auth: Auth):
    store = get_auth_store()
    return {"providers": store.list_user_provider_keys(auth.user_id)}


# ---------------------------------------------------------------------------
# PUT /v1/llm/providers/{provider} — store/update a key
# ---------------------------------------------------------------------------


@router.put("/v1/llm/providers/{provider}")
async def put_provider_key(provider: str, auth: Auth, request: Request):
    body = await request.json()
    provider = provider.strip().lower()

    store = get_auth_store()
    known = store.catalog_providers()
    if provider not in known:
        json_error(
            "validation_failed",
            f'Unknown provider "{provider}". Known providers: {", ".join(known)}.',
            422,
        )

    api_key = str(body["api_key"]) if body.get("api_key") not in (None, "") else None
    _bu = body.get("base_url")
    base_url = str(_bu).strip() or None if isinstance(_bu, str) else None

    existing = store.user_provider_key(auth.user_id, provider)
    if api_key is None and existing is None:
        json_error("missing_field", '"api_key" is required when storing a new provider key.', 400)

    # NULL api_key on update preserves the stored key (COALESCE in the upsert).
    store.upsert_user_provider_key(auth.user_id, provider, api_key, base_url)

    rows = store.list_user_provider_keys(auth.user_id)
    row = next(r for r in rows if r["provider"] == provider)
    return {"provider": {"provider": provider, "key_set": row["key_set"], "base_url": row["base_url"]}}


# ---------------------------------------------------------------------------
# DELETE /v1/llm/providers/{provider}
# ---------------------------------------------------------------------------


@router.delete("/v1/llm/providers/{provider}")
def delete_provider_key(provider: str, auth: Auth):
    provider = provider.strip().lower()
    store = get_auth_store()
    if not store.delete_user_provider_key(auth.user_id, provider):
        json_error("not_found", f'No stored key for provider "{provider}".', 404)
    return {"deleted": True, "provider": provider}


# ---------------------------------------------------------------------------
# GET /v1/llm/models — effective task -> model choices
# ---------------------------------------------------------------------------


@router.get("/v1/llm/models")
def list_model_choices(auth: Auth):
    store = get_auth_store()
    chosen = {c["task"]: c for c in store.list_user_model_choices(auth.user_id)}
    catalog = {(r["model_name"], r["task"]): r for r in store.list_default_prompts()}

    models = []
    for task in store.catalog_tasks():
        c = chosen.get(task)
        if c is not None:
            row = catalog.get((c["model_name"], task))
            models.append(
                {
                    "task": task,
                    "model_name": c["model_name"],
                    "provider": row["provider"] if row else None,
                    "chosen": True,
                    "system_prompt_override": c["system_prompt_override"],
                }
            )
        elif task == "extract":
            # No choice: ingest falls back to the legacy model_prompts default.
            models.append(
                {
                    "task": task,
                    "model_name": _LEGACY_EXTRACT_DEFAULT,
                    "provider": None,
                    "chosen": False,
                    "system_prompt_override": False,
                }
            )
        else:
            # skill_extract: deterministic fallback; embed: env/deterministic.
            models.append(
                {
                    "task": task,
                    "model_name": None,
                    "provider": None,
                    "chosen": False,
                    "system_prompt_override": False,
                }
            )
    return {"models": models}


# ---------------------------------------------------------------------------
# PUT /v1/llm/models/{task} — choose a model for a task
# ---------------------------------------------------------------------------


@router.put("/v1/llm/models/{task}")
async def put_model_choice(task: str, auth: Auth, request: Request):
    body = await request.json()
    task = task.strip().lower()

    model_name = str(body.get("model_name", "")).strip()
    if not model_name:
        json_error("missing_field", '"model_name" is required.', 400)
    _sp = body.get("system_prompt")
    system_prompt = str(_sp) if _sp not in (None, "") else None

    store = get_auth_store()
    row = store.default_prompt(model_name, task)
    if row is None:
        json_error(
            "validation_failed",
            f'Unknown model "{model_name}" for task "{task}". See GET /v1/llm/catalog.',
            422,
        )

    store.upsert_user_model_choice(auth.user_id, task, model_name, system_prompt)

    out: dict = {
        "task": task,
        "model_name": model_name,
        "provider": row["provider"],
        "system_prompt_override": system_prompt is not None,
    }
    key = store.user_provider_key(auth.user_id, row["provider"])
    out["key_set"] = bool(key and key.get("api_key"))
    if not out["key_set"]:
        out["warning"] = (
            f'No API key stored for provider "{row["provider"]}". Set one via PUT /v1/llm/providers/{row["provider"]}.'
        )
    return {"choice": out}


# ---------------------------------------------------------------------------
# DELETE /v1/llm/models/{task} — revert to the server default
# ---------------------------------------------------------------------------


@router.delete("/v1/llm/models/{task}")
def delete_model_choice(task: str, auth: Auth):
    task = task.strip().lower()
    store = get_auth_store()
    if not store.delete_user_model_choice(auth.user_id, task):
        json_error("not_found", f'No model choice stored for task "{task}".', 404)
    return {"deleted": True, "task": task}
