"""
Effective LLM config resolution — per-user task -> model -> connection.

Computes the model configuration a pipeline (memory ingest, skill ingest,
embeddings) should use for a task, layering three sources:

  1. Explicit ``model`` in the request body:
       a. legacy model_prompts row (byte-for-byte today's behavior, including
          its own api_key), else
       b. default_prompts catalog row (model, task) + the caller's provider key.
  2. The user's choice — user_model_choices(user_id, task) -> catalog row +
     provider key, with the user's optional system_prompt and base_url
     overrides.
  3. Nothing matched -> None.  Callers keep their existing legacy fallback
     (the 'chatgpt-4o' model_prompts row, namespace config, env embedding,
     deterministic vectors) so unconfigured tenants see today's exact errors.

The returned dict is shaped like a model_prompts row (the shape memory.py and
skills.py already consume): model_name, model_identifier, api_format, base_url,
api_key, max_tokens, generation_params (JSON string or None), system_prompt,
plus "source" ('model_prompts' | 'catalog_explicit' | 'user_choice').
"""

from __future__ import annotations

from app.auth_store import AuthStore


def _catalog_config(
    store: AuthStore, user_id: int, task: str, row: dict, source: str, prompt_override: str | None = None
) -> dict:
    """Assemble an effective config from a catalog row + the user's provider key."""
    key = store.user_provider_key(user_id, row["provider"])
    return {
        "model_name": row["model_name"],
        "model_identifier": row["model_identifier"],
        "api_format": row["api_format"],
        # The user's per-provider base_url override wins (e.g. self-hosted ollama).
        "base_url": (key or {}).get("base_url") or row["base_url"],
        "api_key": (key or {}).get("api_key"),
        "max_tokens": int(row["max_tokens"] or 2048),
        "generation_params": row.get("generation_params"),
        "system_prompt": prompt_override if prompt_override else row.get("system_prompt"),
        "provider": row["provider"],
        "source": source,
    }


def resolve_task_config(store: AuthStore, user_id: int, task: str, explicit_model: str | None = None) -> dict | None:
    """Resolve the effective LLM config for a task, or None if nothing is set."""
    if explicit_model:
        # 1a. Legacy model_prompts wins for explicit models — existing
        #     deployments that configured this name see zero behavior change.
        pr = store.model_prompt(explicit_model)
        if pr is not None:
            return {**pr, "provider": None, "source": "model_prompts"}
        # 1b. Catalog row for this task.
        row = store.default_prompt(explicit_model, task)
        if row is not None:
            return _catalog_config(store, user_id, task, row, "catalog_explicit")
        return None

    # 2. The user's stored choice for this task.
    choice = store.user_model_choice(user_id, task)
    if choice is not None:
        row = store.default_prompt(choice["model_name"], task)
        if row is not None:
            return _catalog_config(
                store,
                user_id,
                task,
                row,
                "user_choice",
                prompt_override=choice.get("system_prompt"),
            )

    # 3. Nothing resolved — caller falls back to its legacy behavior.
    return None


def resolve_embed_config(store: AuthStore, user_id: int) -> dict:
    """The user's 'embed' choice as a mem_embed() cfg dict; {} when unset.

    mem_embed falls back to MALUDB_EMBED_* env vars and then the deterministic
    vector when the returned dict is empty or incomplete, so this never breaks
    an unconfigured tenant.
    """
    cfg = resolve_task_config(store, user_id, "embed")
    if cfg is None or not cfg.get("api_key"):
        return {}
    return {
        "embedding_base_url": cfg["base_url"],
        "embedding_token": cfg["api_key"],
        "embedding_model": cfg["model_identifier"],
    }
