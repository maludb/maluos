"""
Generic user-table API — PostgREST/Supabase-compatible CRUD over the tenant's
own application tables.

MaluDB is offerable as a hosted DBaaS: clients talk to their own tables over
HTTP with no app server in between. This router reflects ``{table}`` from the
tenant's schema (app/helpers/reflect.py — base tables only, ``maludb_*``/
``malu$*`` rejected) and serves the PostgREST grammar through the shared parser
(app/helpers/query.py). Unlike the hand-written memory routers, the SQL here is
assembled from catalog-reflected identifiers — user tables can't have
hand-written handlers by definition.

One implementation, two mounts:

- ``/rest/v1/{table}``   — wire-compatible with PostgREST, so supabase-js /
  supabase-py clients work unchanged: bare-array responses, PostgREST error
  bodies (``{"code","message","details","hint"}``), ``Prefer:`` headers,
  ``Accept: application/vnd.pgrst.object+json`` for ``.single()``.
- ``/v1/tables/{table}`` — house style: enveloped responses (``{"rows": …}``,
  ``{"inserted": n}``) and the standard ``{"error":{code,message}}`` shape.

Supported surface:

    GET/HEAD  filtering (?col=op.value, or=(), and=(), not.), ?select= (with *
              and aliases), ?order=, limit/offset, Prefer: count=exact|planned|
              estimated + Content-Range
    POST      single object or bulk array; ?columns=; upsert via
              Prefer: resolution=merge-duplicates|ignore-duplicates
              (+ ?on_conflict=, default: primary key); Prefer: return=
    PATCH     body = column:value object; filtered by the same grammar;
              ?order/?limit/?offset window the affected rows (ctid subquery)
    DELETE    filtered by the same grammar; windowed like PATCH

Unknown query-param keys are **rejected** (400) rather than ignored — on a
generic write surface, a typo'd filter (``?idd=eq.5``) silently matching every
row would be a data-loss footgun. For the same reason POST rejects filter
params outright (they don't apply to inserts), and ``debug`` is reserved for
the SQL trace on every method (a column literally named ``debug`` is still
filterable through an ``and=()`` group).

Not implemented (documented gaps): resource embedding (``select=rel(*)``),
``/rpc/{fn}``, JSON-path operators, array operators (cs/cd/ov), ``Range``
headers, CSV bodies.
"""

from __future__ import annotations

import functools

import psycopg
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb

from app.auth import Auth, AuthContext
from app.database import db_exec, db_one, db_query
from app.errors import APIError, _pg_error_message, classify_database_error, json_error
from app.helpers.query import (
    _RESERVED_KEYS,
    ParsedQuery,
    content_range,
    parse_query,
    prefer_token,
    resolve_total,
    split_quoted_list,
    wants_count,
)
from app.helpers.reflect import TableInfo, quote_ident, resolve_table
from app.helpers.writes import as_items

router_rest = APIRouter(prefix="/rest/v1", tags=["rest"])
router_tables = APIRouter(prefix="/v1/tables", tags=["tables"])


# ---------------------------------------------------------------------------
# Prefer / Accept header parsing
# ---------------------------------------------------------------------------

_OBJECT_ACCEPT = "application/vnd.pgrst.object+json"


def wants_return(request: Request) -> str | None:
    """The ``Prefer: return=…`` preference, or None (PostgREST default: minimal)."""
    return prefer_token(request, "return", ("representation", "minimal", "headers-only"))


def wants_resolution(request: Request) -> str | None:
    """The ``Prefer: resolution=…`` upsert preference, or None (plain insert)."""
    return prefer_token(request, "resolution", ("merge-duplicates", "ignore-duplicates"))


def wants_object(request: Request) -> bool:
    """True when the client asked for a single JSON object (supabase ``.single()``)."""
    return _OBJECT_ACCEPT in request.headers.get("accept", "")


async def _read_json(request: Request):
    """Parse the request body, mapping malformed/empty JSON to a clean 400
    (PostgREST behavior) instead of leaking a JSONDecodeError 500."""
    try:
        return await request.json()
    except Exception:  # noqa: BLE001 — any body-parse failure is the client's
        json_error("validation_failed", "Empty or invalid JSON body.", 400)


# ---------------------------------------------------------------------------
# Strict query-key validation
# ---------------------------------------------------------------------------

# Keys the read grammar consumes (derived from the parser's own reserved set,
# so the two can't drift), plus `debug` (the ?debug=1 SQL trace). `debug` is
# also passed to parse_query as reserved= so a tenant column named `debug` can
# never turn the trace flag into a silent filter.
_GRAMMAR_KEYS = frozenset(_RESERVED_KEYS | {"debug"})
_RESERVED = ("debug",)

# POST is not a filtered operation: only these keys are meaningful. `columns`
# and `on_conflict` are reserved from RETURNING-select parsing too, so a table
# column with either name can't shadow the control param.
_INSERT_KEYS = frozenset({"select", "columns", "on_conflict", "debug"})
_INSERT_RESERVED = ("debug", "columns", "on_conflict")


def _check_debug_value(query_params) -> None:
    """`debug` is reserved for the SQL-trace flag (?debug=1). A filter-shaped
    value (?debug=eq.true on a table with a `debug` column) must NOT be
    silently dropped — that would unfilter a write. EVERY occurrence is checked
    (a repeated ?debug=eq.true&debug=1 must not sneak past on the last value).
    Reject and point at the and=() group, which reaches the column
    unambiguously."""
    for value in query_params.getlist("debug"):
        if value not in ("", "0", "1"):
            json_error(
                "bad_request",
                "'debug' is reserved for the SQL trace (?debug=1). "
                "To filter a column named 'debug', use and=(debug.<op>.<value>).",
                400,
            )


def _check_known_keys(query_params, spec) -> None:
    """Reject query keys that are neither grammar keys nor spec columns."""
    _check_debug_value(query_params)
    for key in query_params.keys():
        if key in _GRAMMAR_KEYS:
            continue
        if key not in spec.columns:
            json_error("unknown_column", f"Unknown query parameter or column '{key}'.", 400)


def _check_insert_keys(query_params) -> None:
    """POST allows no filter/order/pagination params — reject them explicitly
    rather than parse-and-ignore (the same footgun class strict checking closes)."""
    _check_debug_value(query_params)
    for key in query_params.keys():
        if key not in _INSERT_KEYS:
            json_error(
                "unknown_column",
                f"Query parameter '{key}' is not allowed on insert (only 'select', 'columns' and 'on_conflict' apply).",
                400,
            )


def _known_column(ti: TableInfo, name: str, where: str) -> str:
    """Validate a client-supplied column name against the reflected table."""
    if name not in ti.data_types:
        json_error("unknown_column", f"Could not find the '{name}' column of '{ti.name}' in {where}.", 400)
    return name


# ---------------------------------------------------------------------------
# SQL builders (unit-testable, no I/O)
# ---------------------------------------------------------------------------


def _adapt(value, data_type: str | None):
    """Bind a JSON body value for the column's reflected type.

    Every non-NULL value destined for a json/jsonb column binds as jsonb —
    including scalars, which PostgREST stores as JSON strings/numbers (a bare
    text/int param would be a Postgres type error). ``None`` stays SQL NULL.
    dicts always bind as jsonb; other values for non-JSON columns pass through
    (notably lists, where psycopg's native list→array adaptation is what an
    ARRAY column expects).
    """
    if value is not None and data_type in ("json", "jsonb"):
        return Jsonb(value)
    if isinstance(value, dict):
        return Jsonb(value)
    return value


def _encode_value(value):
    """bytea → PostgREST-style hex string (``\\x…``), recursing into arrays —
    raw bytes would crash the strict-UTF-8 JSON encoder."""
    if isinstance(value, (bytes, memoryview)):
        return "\\x" + bytes(value).hex()
    if isinstance(value, list):
        return [_encode_value(v) for v in value]
    return value


def _encode_rows(rows: list[dict]) -> list[dict]:
    """Post-process DB rows for JSON: encode bytea (incl. bytea[]) as hex.
    (Other types — datetime, UUID, Decimal — are handled by FastAPI's encoder;
    note Decimal→float is lossy past ~15 digits, a documented divergence.)"""
    for row in rows:
        for key, value in row.items():
            row[key] = _encode_value(value)
    return rows


def build_insert_sql(
    ti: TableInfo,
    items: list[dict],
    columns_param: str | None,
    on_conflict_param: str | None,
    resolution: str | None,
    returning: str | None,
) -> tuple[str, list]:
    """Assemble one multi-row ``INSERT`` (optionally ``ON CONFLICT``) statement.

    Insert columns come from ``?columns=`` when given, else the union of the
    items' keys (missing keys per row insert as ``DEFAULT``). All column names
    are validated against the reflected table and quoted from catalog names.
    """
    if columns_param is not None:
        cols = split_quoted_list(columns_param)
        if not cols:
            json_error("bad_request", "Empty 'columns' list.", 400)
    else:
        cols = []
        for item in items:
            for key in item:
                if key not in cols:
                    cols.append(key)
    for c in cols:
        _known_column(ti, c, "the insert body")

    params: list = []
    if not cols:
        # All items are {} — Postgres only supports DEFAULT VALUES for one row.
        if len(items) != 1:
            json_error("bad_request", "Bulk insert of empty objects is not supported.", 400)
        sql = f"INSERT INTO {ti.ident} DEFAULT VALUES"
    else:
        value_rows: list[str] = []
        for item in items:
            placeholders: list[str] = []
            for c in cols:
                if c in item:
                    placeholders.append("%s")
                    params.append(_adapt(item[c], ti.data_types.get(c)))
                else:
                    placeholders.append("DEFAULT")
            value_rows.append("(" + ", ".join(placeholders) + ")")
        col_list = ", ".join(quote_ident(c) for c in cols)
        sql = f"INSERT INTO {ti.ident} ({col_list}) VALUES {', '.join(value_rows)}"

    if resolution:
        if on_conflict_param:
            target = [_known_column(ti, c, "'on_conflict'") for c in split_quoted_list(on_conflict_param)]
        else:
            target = ti.pk
        if not target:
            json_error(
                "bad_request",
                f"Upsert on '{ti.name}' needs '?on_conflict=' — the table has no primary key.",
                400,
            )
        if resolution == "merge-duplicates" and columns_param is None:
            # A merge-upsert writes EVERY insert column of a conflicting row; a
            # row missing a key would overwrite the stored value with DEFAULT.
            # PostgREST rejects heterogeneous bulk bodies for exactly this
            # reason — but only when ?columns= is absent: an explicit column
            # list (which supabase-js always sends for arrays) is the client
            # opting into DEFAULT-filling missing keys.
            for item in items:
                for c in cols:
                    if c not in item:
                        json_error(
                            "bad_request",
                            f"All object keys must match for a merge-duplicates upsert ('{c}' is missing).",
                            400,
                        )
        target_sql = ", ".join(quote_ident(c) for c in target)
        update_cols = [c for c in cols if c not in target]
        if resolution == "ignore-duplicates" or not update_cols:
            sql += f" ON CONFLICT ({target_sql}) DO NOTHING"
        else:
            set_sql = ", ".join(f"{quote_ident(c)} = EXCLUDED.{quote_ident(c)}" for c in update_cols)
            sql += f" ON CONFLICT ({target_sql}) DO UPDATE SET {set_sql}"

    if returning:
        sql += f" RETURNING {returning}"
    return sql, params


def _window_clause(ti: TableInfo, qp: ParsedQuery, limit: int | None, offset: int | None) -> tuple[str, list]:
    """A ``WHERE ctid IN (…)`` fragment windowing a write to the ordered/limited
    row set — how PostgREST implements limited UPDATE/DELETE.

    ``limit``/``offset`` are the client's EXPLICIT, validated values (see
    ``_write_window``) — qp's parsed limit is never used here because it holds
    a default/clamped value that would silently cap the write.
    """
    inner = f"SELECT ctid FROM {ti.ident} {qp.where_sql} {qp.order_sql}"
    params = list(qp.where_params)
    if limit is not None:
        inner += " LIMIT %s"
        params.append(limit)
    if offset is not None:
        inner += " OFFSET %s"
        params.append(offset)
    return f"WHERE ctid IN ({inner})", params


def build_update_sql(
    ti: TableInfo,
    body: dict,
    qp: ParsedQuery,
    returning: str | None,
    window: tuple[int | None, int | None] | None = None,
) -> tuple[str, list]:
    """Assemble ``UPDATE … SET … [WHERE …]`` from a column:value body + parsed
    filters. ``window=(limit, offset)`` applies the client's explicit,
    validated ?limit/?offset (with ?order) via a ctid subquery."""
    if not body:
        json_error("bad_request", "PATCH body must contain at least one column.", 400)
    set_parts: list[str] = []
    params: list = []
    for key, value in body.items():
        _known_column(ti, key, "the update body")
        set_parts.append(f"{quote_ident(key)} = %s")
        params.append(_adapt(value, ti.data_types.get(key)))
    if window:
        where_sql, where_params = _window_clause(ti, qp, *window)
    else:
        where_sql, where_params = qp.where_sql, list(qp.where_params)
    sql = f"UPDATE {ti.ident} SET {', '.join(set_parts)} {where_sql}"
    params.extend(where_params)
    if returning:
        sql += f" RETURNING {returning}"
    return sql, params


def build_delete_sql(
    ti: TableInfo,
    qp: ParsedQuery,
    returning: str | None,
    window: tuple[int | None, int | None] | None = None,
) -> tuple[str, list]:
    """Assemble ``DELETE FROM … [WHERE …]`` from parsed filters. ``window``
    applies the client's explicit ?limit/?offset via a ctid subquery."""
    if window:
        where_sql, params = _window_clause(ti, qp, *window)
    else:
        where_sql, params = qp.where_sql, list(qp.where_params)
    sql = f"DELETE FROM {ti.ident} {where_sql}"
    if returning:
        sql += f" RETURNING {returning}"
    return sql, params


# ---------------------------------------------------------------------------
# Core operations (flavor-independent)
# ---------------------------------------------------------------------------


def _single_object(rows: list[dict]):
    """Apply the ``.single()`` Accept header: exactly one row or 406."""
    if len(rows) != 1:
        json_error(
            "object_mismatch",
            f"JSON object requested, multiple (or no) rows returned ({len(rows)} rows).",
            406,
        )
    return rows[0]


def _write_window(request: Request, max_limit: int) -> tuple[int | None, int | None] | None:
    """The client's explicit write window as ``(limit, offset)``.

    None when neither param is present (an empty value counts as absent) —
    parse_query always fills a default limit, which must NOT window an
    unqualified bulk write. Non-integer/negative values were already rejected
    by parse_query (which runs first), so only the over-max check lives here:
    the read-side clamp must never silently cap a write (a clamped DELETE
    would leave rows behind while reporting success).
    """
    raw_limit = request.query_params.get("limit")
    raw_offset = request.query_params.get("offset")
    limit = int(raw_limit) if raw_limit else None
    offset = int(raw_offset) if raw_offset else None
    if limit is not None and limit > max_limit:
        json_error("bad_request", f"'limit' must be <= {max_limit} on writes.", 400)
    if limit is None and offset is None:
        return None
    return limit, offset


def _run_write(auth: AuthContext, sql: str, params: list, representation: bool) -> tuple[list[dict] | None, int]:
    """Execute a write statement: RETURNING rows when representation was
    requested, else just the affected-row count."""
    if representation:
        rows = _encode_rows(db_query(auth.conn, sql, params))
        return rows, len(rows)
    return None, db_exec(auth.conn, sql, params)


def _get_core(auth: AuthContext, request: Request, response: Response, table: str) -> list[dict]:
    """Shared read path: reflect, parse, select, count. Returns the row list.

    HEAD discards the body (supabase's count-only ``head: true`` call), so it
    fetches a single windowed count instead of materializing up to max-rows
    rows — the count still drives Content-Range, and the empty body means
    Content-Length is honestly 0 rather than the length of placeholder rows.
    """
    ti = resolve_table(auth.conn, table)
    _check_known_keys(request.query_params, ti.spec)
    qp = parse_query(request.query_params, ti.spec, reserved=_RESERVED)
    total = resolve_total(auth.conn, wants_count(request), ti.ident, qp.where_sql, qp.where_params)
    if request.method == "HEAD":
        inner = f"SELECT 1 FROM {ti.ident} {qp.where_sql} {qp.limit_sql}"
        row = db_one(auth.conn, f"SELECT count(*) AS n FROM ({inner}) w", qp.where_params + qp.limit_params)
        returned = int(row["n"]) if row else 0
        response.headers["Content-Range"] = content_range(qp.offset, returned, total)
        return []
    sql = f"SELECT {qp.select_list} FROM {ti.ident} {qp.where_sql} {qp.order_sql} {qp.limit_sql}"
    rows = _encode_rows(db_query(auth.conn, sql, qp.where_params + qp.limit_params))
    response.headers["Content-Range"] = content_range(qp.offset, len(rows), total)
    return rows


def _insert_core(auth: AuthContext, request: Request, table: str, body) -> tuple[list[dict] | None, int]:
    """Shared insert/upsert path. Returns ``(rows|None, affected)`` — rows only
    when ``Prefer: return=representation``."""
    resolution = wants_resolution(request)
    # The PK is only consulted as the default upsert conflict target — plain
    # inserts skip the second catalog query.
    ti = resolve_table(auth.conn, table, include_pk=resolution is not None)
    _check_insert_keys(request.query_params)
    items, _ = as_items(body)
    representation = wants_return(request) == "representation"
    if not items:
        return ([] if representation else None), 0

    # The RETURNING select list is only needed for representation (or to
    # validate an explicit ?select=); control params are reserved so a column
    # named 'columns'/'on_conflict' can't shadow them.
    returning = None
    if representation or "select" in request.query_params:
        qp = parse_query(request.query_params, ti.spec, reserved=_INSERT_RESERVED)
        returning = qp.select_list if representation else None
    sql, params = build_insert_sql(
        ti,
        items,
        request.query_params.get("columns"),
        request.query_params.get("on_conflict"),
        resolution,
        returning,
    )
    return _run_write(auth, sql, params, representation)


def _update_core(auth: AuthContext, request: Request, table: str, body) -> tuple[list[dict] | None, int]:
    """Shared update path. Returns ``(rows|None, affected)``."""
    ti = resolve_table(auth.conn, table)
    _check_known_keys(request.query_params, ti.spec)
    if not isinstance(body, dict):
        json_error("validation_failed", "PATCH body must be a JSON object of column:value pairs.", 422)
    qp = parse_query(request.query_params, ti.spec, reserved=_RESERVED)
    representation = wants_return(request) == "representation"
    sql, params = build_update_sql(
        ti, body, qp, qp.select_list if representation else None, window=_write_window(request, ti.spec.max_limit)
    )
    return _run_write(auth, sql, params, representation)


def _delete_core(auth: AuthContext, request: Request, table: str) -> tuple[list[dict] | None, int]:
    """Shared delete path. Returns ``(rows|None, affected)``."""
    ti = resolve_table(auth.conn, table)
    _check_known_keys(request.query_params, ti.spec)
    qp = parse_query(request.query_params, ti.spec, reserved=_RESERVED)
    representation = wants_return(request) == "representation"
    sql, params = build_delete_sql(
        ti, qp, qp.select_list if representation else None, window=_write_window(request, ti.spec.max_limit)
    )
    return _run_write(auth, sql, params, representation)


# ---------------------------------------------------------------------------
# PostgREST error shape (rest flavor only — /v1/tables uses the global handlers)
# ---------------------------------------------------------------------------

# Our APIError codes → PostgREST error codes (the ones supabase clients key on).
_PGRST_CODES = {
    "table_not_found": "PGRST205",
    "unknown_column": "PGRST204",
    "object_mismatch": "PGRST116",
    "bad_request": "PGRST100",
    "validation_failed": "PGRST102",
}


def _pgrst_error(exc: Exception) -> JSONResponse:
    """Convert an APIError / psycopg DatabaseError to a PostgREST error body."""
    if isinstance(exc, APIError):
        return JSONResponse(
            status_code=exc.status,
            content={
                "code": _PGRST_CODES.get(exc.code, "PGRST100"),
                "message": exc.message,
                "details": None,
                "hint": None,
            },
        )
    # psycopg DatabaseError → PostgREST passes the SQLSTATE through as the code.
    status, _, sqlstate = classify_database_error(exc)
    diag = getattr(exc, "diag", None)
    return JSONResponse(
        status_code=status,
        content={
            "code": sqlstate or "XX000",
            "message": _pg_error_message(exc),
            "details": getattr(diag, "message_detail", None) if diag else None,
            "hint": getattr(diag, "message_hint", None) if diag else None,
        },
    )


_PGRST_ERRORS = (APIError, psycopg.errors.DatabaseError)


def _pgrst_route(fn):
    """Wrap a /rest/v1 handler so every APIError / DatabaseError leaves as a
    PostgREST error body. Held in one place so a future handler can't forget
    the wire-format guarantee by omitting a copy-pasted try/except. All /rest
    handlers are async (the codebase norm), so one wrapper suffices."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except _PGRST_ERRORS as exc:
            return _pgrst_error(exc)

    return wrapper


def _shape_write(auth: AuthContext, request: Request, run_core):
    """Run a write core, applying the ``.single()`` object contract.

    When the client demands a single object, the write and the cardinality
    check run in ONE transaction so a 406 mismatch rolls the write back —
    matching PostgREST, where an errored request never persists. ``run_core``
    is a no-arg callable returning ``(rows|None, affected)``.
    """
    if wants_object(request) and wants_return(request) == "representation":
        with auth.conn.transaction():
            rows, affected = run_core()
            return _single_object(rows), affected
    rows, affected = run_core()
    return rows, affected


# ---------------------------------------------------------------------------
# /rest/v1 — PostgREST wire-compatible mount
# ---------------------------------------------------------------------------


@router_rest.api_route("/{table}", methods=["GET", "HEAD"])
@_pgrst_route
async def rest_select(table: str, auth: Auth, request: Request, response: Response):
    rows = _get_core(auth, request, response, table)
    if wants_object(request) and request.method != "HEAD":
        return _single_object(rows)
    return rows


@router_rest.post("/{table}", status_code=201)
@_pgrst_route
async def rest_insert(table: str, auth: Auth, request: Request):
    body = await _read_json(request)
    payload, _ = _shape_write(auth, request, lambda: _insert_core(auth, request, table, body))
    return Response(status_code=201) if payload is None else payload


@router_rest.patch("/{table}")
@_pgrst_route
async def rest_update(table: str, auth: Auth, request: Request):
    body = await _read_json(request)
    payload, _ = _shape_write(auth, request, lambda: _update_core(auth, request, table, body))
    return Response(status_code=204) if payload is None else payload


@router_rest.delete("/{table}")
@_pgrst_route
async def rest_delete(table: str, auth: Auth, request: Request):
    payload, _ = _shape_write(auth, request, lambda: _delete_core(auth, request, table))
    return Response(status_code=204) if payload is None else payload


# ---------------------------------------------------------------------------
# /v1/tables — house-style mount (standard envelopes + global error handlers)
# ---------------------------------------------------------------------------


@router_tables.api_route("/{table}", methods=["GET", "HEAD"])
async def tables_select(table: str, auth: Auth, request: Request, response: Response):
    return {"rows": _get_core(auth, request, response, table)}


@router_tables.post("/{table}", status_code=201)
async def tables_insert(table: str, auth: Auth, request: Request):
    rows, affected = _insert_core(auth, request, table, await _read_json(request))
    return {"inserted": affected} if rows is None else {"rows": rows}


@router_tables.patch("/{table}")
async def tables_update(table: str, auth: Auth, request: Request):
    rows, affected = _update_core(auth, request, table, await _read_json(request))
    return {"updated": affected} if rows is None else {"rows": rows}


@router_tables.delete("/{table}")
async def tables_delete(table: str, auth: Auth, request: Request):
    rows, affected = _delete_core(auth, request, table)
    return {"deleted": affected} if rows is None else {"rows": rows}
