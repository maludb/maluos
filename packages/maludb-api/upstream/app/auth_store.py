"""
SQLite auth store — replaces MySQL from the PHP version.

Ports PHP's LocalDatabase class (config/local-database.php): token resolution,
model prompt lookup, and next_user_id.  Schema lives in config/auth_store.sql.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.store_crypto import seal, unseal

# Schema file path (relative to project root)
_SCHEMA_FILE = Path(__file__).resolve().parent.parent / "config" / "auth_store.sql"


class AuthStore:
    """SQLite-backed auth/routing store.

    One instance per process (the FastAPI app keeps a singleton).  All reads
    are synchronous — SQLite is fast enough for a lookup table, and the auth
    check runs once per request.
    """

    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        """Read and execute config/auth_store.sql to create tables if needed,
        then seed the default_prompts catalog (idempotent INSERT OR IGNORE)."""
        from app.llm_catalog import seed_default_prompts

        schema = _SCHEMA_FILE.read_text()
        self._conn.executescript(schema)
        seed_default_prompts(self._conn)

    # ------------------------------------------------------------------
    # Token resolution (called by require_auth)
    # ------------------------------------------------------------------

    def resolve_token(self, token_hash: str) -> dict | None:
        """Look up a user row by sha256 token hash; returns None if unknown or expired.

        Both sides go through SQLite's datetime(): tokens.py stores "YYYY-MM-DD HH:MM:SS" and a
        plain string comparison against an ISO "…T…Z" now sorts the space below the "T", which
        expired every token at 00:00 UTC of its last day — and would kill a short-lived token
        (minutes, not days) the moment it was minted. datetime() reads either spelling.
        """
        cursor = self._conn.execute(
            """
            SELECT user_id, role, pg_dbname, pg_user, pg_password
              FROM users
             WHERE token_hash = ?
               AND (expires_at IS NULL OR datetime(expires_at) > datetime('now'))
             LIMIT 1
            """,
            (token_hash,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        user = dict(row)
        user["pg_password"] = unseal(user["pg_password"])
        return user

    # ------------------------------------------------------------------
    # Next user ID (for token-create when no user_id is supplied)
    # ------------------------------------------------------------------

    def next_user_id(self) -> int:
        """Return MAX(user_id) + 1, or 1 if the table is empty."""
        cursor = self._conn.execute("SELECT COALESCE(MAX(user_id), 0) + 1 AS n FROM users")
        row = cursor.fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------
    # Model prompt lookup (for LLM pipeline)
    # ------------------------------------------------------------------

    def model_prompt(self, model_name: str) -> dict | None:
        """Load the per-model extraction prompt + LLM connection, or None."""
        cursor = self._conn.execute(
            """
            SELECT model_name, model_identifier, api_format, system_prompt,
                   base_url, api_key, max_tokens, generation_params
              FROM model_prompts
             WHERE model_name = ?
             LIMIT 1
            """,
            (model_name,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        prompt = dict(row)
        prompt["api_key"] = unseal(prompt["api_key"])
        return prompt

    # ------------------------------------------------------------------
    # Default-prompt catalog (seeded by app/llm_catalog.py)
    # ------------------------------------------------------------------

    def default_prompt(self, model_name: str, task: str) -> dict | None:
        """Load the catalog row for (model_name, task), or None."""
        cursor = self._conn.execute(
            """
            SELECT provider, model_name, model_identifier, api_format, base_url,
                   task, system_prompt, max_tokens, generation_params
              FROM default_prompts
             WHERE model_name = ? AND task = ?
             LIMIT 1
            """,
            (model_name, task),
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else None

    def list_default_prompts(self) -> list[dict]:
        """All catalog rows (without the prompt text — it can be large)."""
        cursor = self._conn.execute(
            """
            SELECT provider, model_name, model_identifier, api_format, base_url,
                   task, max_tokens,
                   (system_prompt IS NOT NULL AND system_prompt <> '') AS has_system_prompt
              FROM default_prompts
             ORDER BY task, provider, model_name
            """
        )
        return [dict(r) for r in cursor.fetchall()]

    def catalog_providers(self) -> list[str]:
        """Distinct providers present in the catalog."""
        cursor = self._conn.execute("SELECT DISTINCT provider FROM default_prompts ORDER BY provider")
        return [r["provider"] for r in cursor.fetchall()]

    def catalog_tasks(self) -> list[str]:
        """Distinct tasks present in the catalog."""
        cursor = self._conn.execute("SELECT DISTINCT task FROM default_prompts ORDER BY task")
        return [r["task"] for r in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Per-user provider API keys
    # ------------------------------------------------------------------

    def user_provider_key(self, user_id: int, provider: str) -> dict | None:
        """The user's key row for a provider (includes api_key — internal use only)."""
        cursor = self._conn.execute(
            "SELECT provider, api_key, base_url FROM user_provider_keys WHERE user_id = ? AND provider = ? LIMIT 1",
            (user_id, provider),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        key = dict(row)
        key["api_key"] = unseal(key["api_key"])
        return key

    def list_user_provider_keys(self, user_id: int) -> list[dict]:
        """The user's providers — key value never selected, only key_set."""
        cursor = self._conn.execute(
            """
            SELECT provider,
                   (api_key IS NOT NULL AND api_key <> '') AS key_set,
                   base_url, updated_at
              FROM user_provider_keys
             WHERE user_id = ?
             ORDER BY provider
            """,
            (user_id,),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        for r in rows:
            r["key_set"] = bool(r["key_set"])
        return rows

    def upsert_user_provider_key(
        self, user_id: int, provider: str, api_key: str | None, base_url: str | None
    ) -> None:
        """Insert or update a provider key.  A None api_key on update preserves
        the stored key (same convention as /v1/model-prompts)."""
        if api_key is None:
            existing = self.user_provider_key(user_id, provider)
            api_key = (existing or {}).get("api_key")
        self._conn.execute(
            """
            INSERT INTO user_provider_keys (user_id, provider, api_key, base_url)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, provider) DO UPDATE SET
                api_key    = excluded.api_key,
                base_url   = excluded.base_url,
                updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            """,
            (user_id, provider, seal(api_key), base_url),  # sealed at rest when MALUDB_STORE_KEY is set
        )
        self._conn.commit()

    def delete_user_provider_key(self, user_id: int, provider: str) -> bool:
        """Delete a provider key; returns True if a row was removed."""
        cur = self._conn.execute(
            "DELETE FROM user_provider_keys WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Per-user task -> model choices
    # ------------------------------------------------------------------

    def user_model_choice(self, user_id: int, task: str) -> dict | None:
        """The user's model choice for a task, or None."""
        cursor = self._conn.execute(
            "SELECT task, model_name, system_prompt FROM user_model_choices"
            " WHERE user_id = ? AND task = ? LIMIT 1",
            (user_id, task),
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else None

    def list_user_model_choices(self, user_id: int) -> list[dict]:
        """All of the user's task -> model choices."""
        cursor = self._conn.execute(
            """
            SELECT task, model_name,
                   (system_prompt IS NOT NULL AND system_prompt <> '') AS system_prompt_override,
                   updated_at
              FROM user_model_choices
             WHERE user_id = ?
             ORDER BY task
            """,
            (user_id,),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        for r in rows:
            r["system_prompt_override"] = bool(r["system_prompt_override"])
        return rows

    def upsert_user_model_choice(
        self, user_id: int, task: str, model_name: str, system_prompt: str | None
    ) -> None:
        """Insert or replace the user's model choice for a task."""
        self._conn.execute(
            """
            INSERT INTO user_model_choices (user_id, task, model_name, system_prompt)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, task) DO UPDATE SET
                model_name    = excluded.model_name,
                system_prompt = excluded.system_prompt,
                updated_at    = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            """,
            (user_id, task, model_name, system_prompt),
        )
        self._conn.commit()

    def delete_user_model_choice(self, user_id: int, task: str) -> bool:
        """Delete the user's model choice for a task; True if a row was removed."""
        cur = self._conn.execute(
            "DELETE FROM user_model_choices WHERE user_id = ? AND task = ?",
            (user_id, task),
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Raw connection (for testing / admin endpoints)
    # ------------------------------------------------------------------

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn
