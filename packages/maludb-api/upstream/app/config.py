"""
Settings from environment variables.

Mirrors the PHP config/database.php + config/response.php config flags.
PG_HOST and PG_PORT are fixed for all tenants; per-request credentials
(dbname, user, password) are resolved from the SQLite auth store keyed
by the API token.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root (one level up from this file's directory)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# PostgreSQL — host/port are deployment-wide; per-tenant creds come from
# the auth store at request time.
# ---------------------------------------------------------------------------
PG_HOST: str = os.environ.get("MALUDB_PG_HOST", "localhost")
PG_PORT: int = int(os.environ.get("MALUDB_PG_PORT", "5432"))

# ---------------------------------------------------------------------------
# SQLite auth store (replaces MySQL from the PHP version)
# ---------------------------------------------------------------------------
AUTH_STORE_PATH: str = os.environ.get(
    "MALUDB_AUTH_STORE",
    str(PROJECT_ROOT / "data" / "auth.db"),
)

# ---------------------------------------------------------------------------
# Debug mode — enables ?debug=1 SQL-trace injection into JSON responses
# ---------------------------------------------------------------------------
DEBUG_ENABLED: bool = os.environ.get("MALUDB_DEBUG") == "1"

# ---------------------------------------------------------------------------
# Logging directory — default /var/log/maludb; fallback to project-local
# var/log/ when the default isn't writable (dev without root).
# ---------------------------------------------------------------------------

def _resolve_log_dir() -> str:
    preferred = os.environ.get("MALUDB_LOG_DIR", "/var/log/maludb")
    if os.path.isdir(preferred) and os.access(preferred, os.W_OK):
        return preferred
    fallback = str(PROJECT_ROOT / "var" / "log")
    os.makedirs(fallback, exist_ok=True)
    if os.access(fallback, os.W_OK):
        return fallback
    import tempfile
    return tempfile.gettempdir()

LOG_DIR: str = _resolve_log_dir()

# ---------------------------------------------------------------------------
# LLM / memory pipeline (used by later routers)
# ---------------------------------------------------------------------------
LLM_TOKEN: str | None = os.environ.get("MALUDB_LLM_TOKEN") or None
EMBED_DIM: int = int(os.environ.get("MALUDB_EMBED_DIM", "1536"))
