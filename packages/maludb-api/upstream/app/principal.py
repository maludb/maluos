"""
Who is asking — the per-request principal (maludb_core 0.106.0).

From 0.106.0 the engine enforces scopes inside a tenant when the session names a principal:

    maludb_core.principal_ref       who ("agent:44", "member:1")
    maludb_core.principal_scopes    optional JSON list that NARROWS the principal's stored grants
    maludb_core.principal_readonly  refuse every scoped write

A host that holds the tenant token sets them per request with three headers:

    X-MaluDB-Principal: agent:44
    X-MaluDB-Scopes: agent:44, dept:3        (comma-separated, or a JSON array)
    X-MaluDB-Readonly: true

No header = unrestricted, exactly as before. The headers can only RESTRICT what the token may do —
the engine intersects the scope list with the grants it holds for that principal — so trusting
them from the token holder gives nothing away. (A delegated token, when those exist, will carry
the same three values itself and ignore the headers.)

Every request has its own Postgres connection (see require_auth), so the settings are made at
session level on that connection and die with it. On an engine older than 0.106.0 they are inert
placeholders; `principal_enforced()` tells a route whether the engine will actually honour them,
and a request that names a principal against an engine that will not is REFUSED rather than
silently served unrestricted.
"""

from __future__ import annotations

import json
import re

import psycopg

from app.errors import json_error

REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.\-@]{0,119}$")
SCOPE = re.compile(r"^[^\s,\[\]\"'][^,\[\]\"']{0,199}$")
MAX_SCOPES = 200
_TRUE = {"1", "true", "on", "yes"}


def parse_scopes(raw: str | None) -> list[str] | None:
    """The X-MaluDB-Scopes header as a list, or None when absent. Raises APIError(400) when unreadable."""
    if raw is None or not raw.strip():
        return None
    text = raw.strip()
    if text.startswith("["):
        try:
            items = json.loads(text)
        except ValueError:
            json_error("invalid_principal", "X-MaluDB-Scopes is not a JSON array.", 400)
        if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
            json_error("invalid_principal", "X-MaluDB-Scopes must be an array of strings.", 400)
    else:
        items = text.split(",")
    scopes: list[str] = []
    for item in items:
        scope = item.strip()
        if not scope:
            continue
        if not SCOPE.match(scope):
            json_error("invalid_principal", f"X-MaluDB-Scopes: '{scope}' is not a scope name.", 400)
        if scope not in scopes:
            scopes.append(scope)
    if len(scopes) > MAX_SCOPES:
        json_error("invalid_principal", f"X-MaluDB-Scopes lists more than {MAX_SCOPES} scopes.", 400)
    return scopes


def principal_enforced(conn: psycopg.Connection) -> bool:
    """True when this tenant's facades are 0.106.0 or later (maludb_principal_whoami exists)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regprocedure(quote_ident(current_schema()) || '.maludb_principal_whoami()') IS NOT NULL AS ok"
        )
        row = cur.fetchone()
    return bool(row and row["ok"])


def apply_principal(conn: psycopg.Connection, headers) -> str | None:
    """Bind the request's connection to the principal its headers name. Returns the ref, or None."""
    ref = (headers.get("x-maludb-principal") or "").strip()
    scopes = parse_scopes(headers.get("x-maludb-scopes"))
    readonly = (headers.get("x-maludb-readonly") or "").strip().lower() in _TRUE
    if not ref:
        if scopes is not None or readonly:
            json_error("invalid_principal", "X-MaluDB-Scopes / X-MaluDB-Readonly need X-MaluDB-Principal.", 400)
        return None
    if not REF.match(ref):
        json_error("invalid_principal", "X-MaluDB-Principal is not a principal reference.", 400)
    if not principal_enforced(conn):
        json_error(
            "principal_unsupported",
            "This tenant's engine does not enforce principals (needs maludb_core 0.106.0 and a re-run of "
            "enable_memory_schema). Refusing to serve a scoped request unscoped.",
            501,
        )
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('maludb_core.principal_ref', %s, false)", [ref])
        cur.execute(
            "SELECT set_config('maludb_core.principal_scopes', %s, false)",
            ["" if scopes is None else json.dumps(scopes)],
        )
        cur.execute("SELECT set_config('maludb_core.principal_readonly', %s, false)", ["on" if readonly else ""])
    return ref
