"""
Error handling — APIError exception, json_error() helper, and exception-to-JSON-response
handlers for FastAPI.

Ports PHP's json_error(), handle_uncaught(), and pg_error_message() from config/response.php.
Standard JSON shape: {"error": {"code": "...", "message": "..."}}
"""

from __future__ import annotations

import re

from fastapi import Request
from fastapi.responses import JSONResponse

from app import config

# ---------------------------------------------------------------------------
# APIError — the application-level exception raised by json_error()
# ---------------------------------------------------------------------------

class APIError(Exception):
    """Raised to abort the request with a structured JSON error response."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def json_error(code: str, message: str, status: int = 400) -> None:
    """Raise an APIError — mirrors PHP's json_error() which calls exit()."""
    raise APIError(code, message, status)


# ---------------------------------------------------------------------------
# Exception → JSON response handlers (registered on the FastAPI app)
# ---------------------------------------------------------------------------

async def api_error_handler(_request: Request, exc: APIError) -> JSONResponse:
    """Handle APIError → standard JSON error response."""
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


def _pg_error_message(exc: Exception) -> str:
    """Build a human-readable message from a psycopg/Postgres error.

    Prefers the structured ``diag`` fields (primary message, detail, hint) that
    psycopg v3 exposes; falls back to parsing the ``ERROR: ...`` line out of the
    raw string. Detail/hint are appended because Postgres puts the actionable
    part there (e.g. which key conflicted, what the valid values are).
    """
    diag = getattr(exc, "diag", None)
    if diag is not None and getattr(diag, "message_primary", None):
        parts = [diag.message_primary.strip()]
        detail = getattr(diag, "message_detail", None)
        hint = getattr(diag, "message_hint", None)
        if detail:
            parts.append(detail.strip())
        if hint:
            parts.append(f"Hint: {hint.strip()}")
        return " ".join(parts)

    msg = str(exc)
    m = re.search(r"ERROR:\s*(.+?)(\n|$)", msg, re.DOTALL)
    return m.group(1).strip() if m else msg.strip()


# ---------------------------------------------------------------------------
# SQLSTATE → (HTTP status, error code) mapping
#
# Exact codes take priority; otherwise we fall back to the two-character
# SQLSTATE *class*. This turns what used to be an opaque 500 into a specific,
# actionable error for the whole Postgres error space. The original PHP-mirrored
# mappings are preserved (23505→409 conflict, 42501→403, the validation set→422)
# so the contract is unchanged; everything else is newly classified.
# ---------------------------------------------------------------------------

# Exact SQLSTATE overrides.
_SQLSTATE_EXACT: dict[str, tuple[int, str]] = {
    # Integrity constraint violations
    "23505": (409, "conflict"),                 # unique_violation
    "23503": (422, "validation_failed"),        # foreign_key_violation
    "23502": (422, "validation_failed"),        # not_null_violation
    "23514": (422, "validation_failed"),        # check_violation
    # Data exceptions
    "22000": (422, "validation_failed"),        # data_exception (generic)
    "22023": (422, "validation_failed"),        # invalid_parameter_value
    "22P02": (422, "validation_failed"),        # invalid_text_representation
    # PL/pgSQL RAISE (custom business-rule errors from facade functions)
    "P0001": (422, "validation_failed"),        # raise_exception
    # Access / privilege
    "42501": (403, "insufficient_privilege"),   # insufficient_privilege
    # Undefined database objects — almost always a schema/search_path/migration
    # mismatch on the server side (this is the class the search_path bug hit).
    "42P01": (500, "schema_error"),             # undefined_table
    "42703": (500, "schema_error"),             # undefined_column
    "42883": (500, "schema_error"),             # undefined_function
    "42P02": (500, "schema_error"),             # undefined_parameter
    "3F000": (500, "schema_error"),             # invalid_schema_name
    # Transaction concurrency — retryable by the client.
    "40001": (409, "serialization_failure"),    # serialization_failure
    "40P01": (409, "deadlock_detected"),        # deadlock_detected
    "55P03": (409, "lock_not_available"),       # lock_not_available
    # Resource / operator
    "53300": (503, "too_many_connections"),     # too_many_connections
    "57014": (503, "query_canceled"),           # query_canceled (timeout)
}

# SQLSTATE class (first two chars) → fallback mapping.
_SQLSTATE_CLASS: dict[str, tuple[int, str]] = {
    "08": (503, "database_unavailable"),        # connection exception
    "22": (422, "validation_failed"),           # data exception
    "23": (422, "constraint_violation"),        # integrity constraint violation
    "40": (409, "transaction_conflict"),        # transaction rollback
    "42": (500, "query_error"),                 # syntax error / access rule violation
    "53": (503, "insufficient_resources"),      # insufficient resources
    "54": (500, "program_limit_exceeded"),      # program limit exceeded
    "57": (503, "operator_intervention"),       # operator intervention
    "58": (503, "system_error"),                # system error (external to PG)
    "XX": (500, "internal_database_error"),     # internal error
}


def classify_database_error(exc: Exception) -> tuple[int, str, str | None]:
    """Map a psycopg DatabaseError to (http_status, error_code, sqlstate).

    Resolution order: exact SQLSTATE, then the two-character class, then a final
    generic 500. Shared by the FastAPI exception handler and the MCP dispatcher.
    """
    # psycopg v3 exceptions carry sqlstate as exc.sqlstate (or via diag).
    sqlstate: str | None = getattr(exc, "sqlstate", None)
    if sqlstate is None:
        diag = getattr(exc, "diag", None)
        if diag is not None:
            sqlstate = getattr(diag, "sqlstate", None)

    if sqlstate and sqlstate in _SQLSTATE_EXACT:
        status, code = _SQLSTATE_EXACT[sqlstate]
    elif sqlstate and sqlstate[:2] in _SQLSTATE_CLASS:
        status, code = _SQLSTATE_CLASS[sqlstate[:2]]
    else:
        status, code = 500, "internal_error"
    return status, code, sqlstate


async def database_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Handle psycopg.errors.DatabaseError → map SQLSTATE to a specific HTTP error.

    The real Postgres message and the SQLSTATE are always included so the
    failure is debuggable instead of an opaque "unexpected error".
    """
    status, code, sqlstate = classify_database_error(exc)

    error: dict[str, str] = {"code": code, "message": _pg_error_message(exc)}
    if sqlstate:
        error["sqlstate"] = sqlstate

    return JSONResponse(status_code=status, content={"error": error})


async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler for any non-DB Python exception.

    Without this, an unexpected error (KeyError, ValueError, a bug in a handler)
    escapes as Starlette's bare HTML "Internal Server Error", breaking the JSON
    contract. Here we always return the standard JSON shape and the exception
    type; the full message is included only when MALUDB_DEBUG is enabled, to
    avoid leaking internals in production.
    """
    detail = str(exc) if config.DEBUG_ENABLED else "An unexpected error occurred."
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": detail,
                "exception": type(exc).__name__,
            }
        },
    )


async def store_key_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """StoreKeyError → 503. The auth store holds sealed secrets this process cannot open
    (MALUDB_STORE_KEY missing or wrong). An operator problem, not the caller's: say so plainly —
    the message names the setting and never a secret."""
    return JSONResponse(
        status_code=503,
        content={"error": {"code": "store_key_unavailable", "message": str(exc)}},
    )


async def secret_format_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """SecretFormatError → 422: the secret as given cannot be stored."""
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "validation_failed", "message": str(exc)}},
    )


async def tenant_db_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """
    Handle TenantDatabaseError → 502 (auth failure) or 503 (unavailable).

    Mirrors PHP's handle_uncaught() TenantDatabaseException branch.
    """
    from app.database import TenantDatabaseError

    assert isinstance(exc, TenantDatabaseError)  # noqa: S101
    if exc.is_auth_failure:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "code": "tenant_db_auth_failed",
                    "message": "The database credentials stored for this API token were rejected by Postgres.",
                }
            },
        )
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "tenant_db_unavailable",
                "message": "The tenant database is currently unavailable.",
            }
        },
    )
