"""TLS to a PostgreSQL on another server (MaluOS Phase 14, the database server).

asyncpg takes `ssl=`: a mode name, or an SSLContext when the server's certificate is to be verified against a
file. The keys are the kernel's own (config/.env: DB_SSLMODE, DB_SSLROOTCERT; runner.env: RUNNER_DB_SSLMODE,
RUNNER_DB_SSLROOTCERT), libpq's names for the same things. Unset: nothing is passed and asyncpg's default holds
(a local database).
"""
from __future__ import annotations

import ssl

MODES = ("disable", "allow", "prefer", "require", "verify-ca", "verify-full")


def ssl_kwargs(mode: str | None, rootcert: str | None) -> dict:
    mode = (mode or "").strip()
    if mode not in MODES:
        return {}
    rootcert = (rootcert or "").strip()
    if mode in ("verify-ca", "verify-full") and rootcert:
        ctx = ssl.create_default_context(cafile=rootcert)
        ctx.check_hostname = mode == "verify-full"
        return {"ssl": ctx}
    return {"ssl": mode}
