"""
Seeded LLM model catalog — default prompts for common models.

Populates the auth store's ``default_prompts`` table so a fresh install offers
working model configurations out of the box: a user only has to store their
provider API key (PUT /v1/llm/providers/{provider}) and pick a model
(PUT /v1/llm/models/{task}).

Seeding rules:
  - Runs on every AuthStore.init_db() — INSERT OR IGNORE on the
    UNIQUE(model_name, task) key, so it is idempotent and additive: upgrades
    add new rows but never overwrite a row an operator hand-edited.
  - To *revise* a shipped prompt, add a new model_name (or write an explicit
    migration); silently changing seeded rows under operators is not allowed.

Prompt files live in config/prompts/ (identical content across the Python,
PHP, and Fastify servers):
  - extract.rich.system.txt    — full ingest-extraction contract, for capable models
  - extract.simple.system.txt  — condensed contract, for small/local models
  - skill-extract.system.txt   — skill discovery-tag extraction
  - query-parse.system.txt     — note-search free-text query parse (verb + subject)
Embedding rows ('embed' task) have no prompt.
"""

from __future__ import annotations

import sqlite3
from functools import lru_cache

from app import config

_PROMPT_DIR = config.PROJECT_ROOT / "config" / "prompts"

# Tasks the servers run today.  The task column is a free string — new tasks
# only need new seed rows and a pipeline that asks for them.
TASKS = ("extract", "skill_extract", "embed", "query_parse", "answer")

# generation_params presets (stored as JSON strings, merged into the request).
_GP_JSON = '{"temperature": 0.1, "response_format": {"type": "json_object"}}'
_GP_TEMP = '{"temperature": 0.1}'

# Chat models: (provider, model_name, model_identifier, api_format, base_url,
#               extract_prompt_file, max_tokens, generation_params)
# Each gets four rows: task 'extract' (with its extract prompt), task
# 'skill_extract' (always skill-extract.system.txt), task 'query_parse'
# (always query-parse.system.txt) and task 'answer' (no prompt of its own: POST /v1/memory/answer
# builds its prompt from the caller's guidelines and its fixed rules).
# Base-URL convention follows app/helpers/llm.py: the openai format appends
# /chat/completions (base ends in /v1), the anthropic format appends
# /v1/messages (base is the bare host).
_CHAT_MODELS = [
    ("openai", "gpt-4o", "gpt-4o", "openai", "https://api.openai.com/v1", "extract.rich.system.txt", 2048, _GP_JSON),
    (
        "openai",
        "gpt-4o-mini",
        "gpt-4o-mini",
        "openai",
        "https://api.openai.com/v1",
        "extract.simple.system.txt",
        2048,
        _GP_JSON,
    ),
    (
        "anthropic",
        "claude-opus",
        "claude-opus-4-8",
        "anthropic",
        "https://api.anthropic.com",
        "extract.rich.system.txt",
        4096,
        None,
    ),
    (
        "anthropic",
        "claude-sonnet",
        "claude-sonnet-4-6",
        "anthropic",
        "https://api.anthropic.com",
        "extract.rich.system.txt",
        4096,
        None,
    ),
    (
        "anthropic",
        "claude-haiku",
        "claude-haiku-4-5",
        "anthropic",
        "https://api.anthropic.com",
        "extract.simple.system.txt",
        4096,
        None,
    ),
    (
        "google",
        "gemini-flash",
        "gemini-2.5-flash",
        "openai",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "extract.simple.system.txt",
        2048,
        _GP_JSON,
    ),
    ("xai", "grok", "grok-4", "openai", "https://api.x.ai/v1", "extract.rich.system.txt", 2048, _GP_JSON),
    (
        "deepseek",
        "deepseek-chat",
        "deepseek-chat",
        "openai",
        "https://api.deepseek.com/v1",
        "extract.rich.system.txt",
        2048,
        _GP_JSON,
    ),
    (
        "ollama",
        "ollama-local",
        "llama3.1",
        "openai",
        "http://localhost:11434/v1",
        "extract.simple.system.txt",
        2048,
        _GP_TEMP,
    ),
]

# Embedding models: (provider, model_name, model_identifier, base_url).
# api_format is 'openai' (the only embeddings shape we speak); no prompt.
_EMBED_MODELS = [
    ("openai", "text-embedding-3-small", "text-embedding-3-small", "https://api.openai.com/v1"),
    ("ollama", "ollama-embed", "nomic-embed-text", "http://localhost:11434/v1"),
]


@lru_cache(maxsize=8)
def _prompt_text(filename: str) -> str:
    """Read a prompt file from config/prompts/ (cached per process)."""
    return (_PROMPT_DIR / filename).read_text()


def seed_rows() -> list[dict]:
    """The full seed matrix as a list of default_prompts row dicts."""
    rows: list[dict] = []
    for provider, name, ident, fmt, base, extract_file, max_tokens, gen in _CHAT_MODELS:
        rows.append(
            {
                "provider": provider,
                "model_name": name,
                "model_identifier": ident,
                "api_format": fmt,
                "base_url": base,
                "task": "extract",
                "system_prompt": _prompt_text(extract_file),
                "max_tokens": max_tokens,
                "generation_params": gen,
            }
        )
        rows.append(
            {
                "provider": provider,
                "model_name": name,
                "model_identifier": ident,
                "api_format": fmt,
                "base_url": base,
                "task": "skill_extract",
                "system_prompt": _prompt_text("skill-extract.system.txt"),
                "max_tokens": max_tokens,
                "generation_params": gen,
            }
        )
        rows.append(
            {
                "provider": provider,
                "model_name": name,
                "model_identifier": ident,
                "api_format": fmt,
                "base_url": base,
                "task": "query_parse",
                "system_prompt": _prompt_text("query-parse.system.txt"),
                "max_tokens": 256,
                "generation_params": gen,
            }
        )
        rows.append(
            {
                "provider": provider,
                "model_name": name,
                "model_identifier": ident,
                "api_format": fmt,
                "base_url": base,
                "task": "answer",
                "system_prompt": None,
                "max_tokens": max_tokens,
                "generation_params": gen,
            }
        )
    for provider, name, ident, base in _EMBED_MODELS:
        rows.append(
            {
                "provider": provider,
                "model_name": name,
                "model_identifier": ident,
                "api_format": "openai",
                "base_url": base,
                "task": "embed",
                "system_prompt": None,
                "max_tokens": 0,
                "generation_params": None,
            }
        )
    return rows


def seed_default_prompts(conn: sqlite3.Connection) -> int:
    """Insert the seed matrix into default_prompts; returns rows inserted.

    INSERT OR IGNORE on UNIQUE(model_name, task): existing rows (including
    operator-edited ones) are left untouched.
    """
    inserted = 0
    for r in seed_rows():
        cur = conn.execute(
            """INSERT OR IGNORE INTO default_prompts
                   (provider, model_name, model_identifier, api_format, base_url,
                    task, system_prompt, max_tokens, generation_params)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["provider"],
                r["model_name"],
                r["model_identifier"],
                r["api_format"],
                r["base_url"],
                r["task"],
                r["system_prompt"],
                r["max_tokens"],
                r["generation_params"],
            ),
        )
        inserted += cur.rowcount if cur.rowcount > 0 else 0
    conn.commit()
    return inserted
