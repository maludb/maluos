-- SQLite auth/routing store for the MaluDB Python API.
--
-- Replaces the MySQL store from the PHP version (config/local-database.sql).
-- One row per API token: it carries the user's role and the Postgres connection
-- (pg_dbname / pg_user / pg_password) that requests authenticated by that token
-- connect with.  The token itself is stored only as a sha256 hash (of the token
-- after the `malu_` prefix).

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash      TEXT    NOT NULL UNIQUE,
    token_prefix    TEXT    NOT NULL,
    user_id         INTEGER NOT NULL,
    role            TEXT    NOT NULL DEFAULT 'executor',
    pg_dbname       TEXT    NOT NULL,
    pg_user         TEXT    NOT NULL,
    pg_password     TEXT    NOT NULL,
    expires_at      TEXT,
    device_name     TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Per-model extraction prompts + LLM connection.  The system prompt may differ
-- per model; api_format selects the request shape ('openai' | 'anthropic').
CREATE TABLE IF NOT EXISTS model_prompts (
    model_name       TEXT PRIMARY KEY,
    model_identifier TEXT,
    api_format       TEXT NOT NULL DEFAULT 'openai',
    system_prompt    TEXT,
    base_url         TEXT,
    api_key          TEXT,
    max_tokens       INTEGER DEFAULT 2048,
    generation_params TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Seeded catalog of default model configurations, one row per (model, task).
-- Seeded at startup by app/llm_catalog.py (INSERT OR IGNORE — re-seeding never
-- overwrites a row an operator hand-edited).  No api_key here: users attach
-- their own provider keys in user_provider_keys.
CREATE TABLE IF NOT EXISTS default_prompts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    provider          TEXT    NOT NULL,                  -- 'openai' | 'anthropic' | 'google' | 'xai' | 'deepseek' | 'ollama'
    model_name        TEXT    NOT NULL,                  -- lookup key (the `model` request value / choice value)
    model_identifier  TEXT    NOT NULL,                  -- actual API model id (e.g. 'gpt-4o')
    api_format        TEXT    NOT NULL DEFAULT 'openai', -- 'openai' | 'anthropic'
    base_url          TEXT    NOT NULL,
    task              TEXT    NOT NULL,                  -- 'extract' | 'skill_extract' | 'embed' (free string)
    system_prompt     TEXT,                              -- NULL for 'embed' rows
    max_tokens        INTEGER NOT NULL DEFAULT 2048,
    generation_params TEXT,                              -- JSON merged into the request body
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (model_name, task)
);

-- One LLM provider API key per user.  Config is keyed by user_id (not token):
-- a user may hold several tokens that all share the same provider keys.
CREATE TABLE IF NOT EXISTS user_provider_keys (
    user_id    INTEGER NOT NULL,
    provider   TEXT    NOT NULL,
    api_key    TEXT    NOT NULL,
    base_url   TEXT,                                     -- optional per-user override (e.g. self-hosted ollama)
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (user_id, provider)
);

-- The user's model choice per task, with an optional system-prompt override.
CREATE TABLE IF NOT EXISTS user_model_choices (
    user_id       INTEGER NOT NULL,
    task          TEXT    NOT NULL,
    model_name    TEXT    NOT NULL,                      -- must exist in default_prompts for this task
    system_prompt TEXT,                                  -- NULL = use the catalog prompt
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (user_id, task)
);
