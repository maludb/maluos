"""
PostgREST-compatible query parsing for list endpoints.

Supabase exposes every table through PostgREST's query grammar (``?col=eq.x``,
``?select=…``, ``?order=…``, ``limit``/``offset``).  This helper brings the same
ergonomics to our hand-written routers **without** abandoning the SQL-traceability
principle: the router keeps writing the literal ``SELECT … FROM …`` text, and this
module only builds the *column projection*, the ``WHERE`` clause, the ``ORDER BY``,
and ``LIMIT``/``OFFSET`` — each constrained to a per-router allowlist (``QuerySpec``)
so **client input never becomes a SQL identifier**.  Values are always bound as
``%s`` placeholders; only operators and (allowlisted) column expressions are
spliced into the SQL text.

Supported grammar (a pragmatic subset of PostgREST):

    filtering   ?col=op.value         op ∈ eq neq gt gte lt lte
                                          like ilike match imatch in is
                                          fts plfts phfts wfts
                negation              ?col=not.op.value
                repeated (AND)        ?age=gte.18&age=lte.65
                OR groups             ?or=(col.op.value,col.op.value)
    selection   ?select=col,alias:col,*
    ordering    ?order=col[.asc|.desc][.nullsfirst|.nullslast],...
    pagination  ?limit=N&offset=M

Two dialects, selected by ``QuerySpec.strict``:

- **Lenient** (default — the hand-written memory routers): the pre-existing
  contract. Values without a known operator prefix are implicit-eq literals,
  quotes are literal characters, aliases are spliced bare (case-folded).
- **Strict** (the reflected user-table API): PostgREST semantics. An operator
  prefix is required (an unknown/typo'd operator is a 400, never a silent
  no-match literal); ``in.()`` and or=()/and=() conditions accept
  PostgREST-quoted values with backslash escaping and malformed quoting is a
  400; aliases are quoted so JSON keys keep their exact case.

Not implemented in either dialect: array/range operators (cs/cd/ov and
friends — 400 in strict, implicit-eq in lenient), op(any)/op(all) modifiers
(400 in strict, parsed-and-ignored in lenient as on main), JSON-path access,
and nested ``and``/``or`` groups.

Malformed values, unknown columns, and unknown operators raise
``APIError("bad_request", …, 400)`` so the failure matches the standard JSON error
shape instead of leaking a Postgres error.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.errors import APIError

# ---------------------------------------------------------------------------
# Spec types — each router declares one of these (DB expression ↔ API field)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Col:
    """One allowlisted, queryable column.

    ``expr`` is the raw SQL expression (e.g. ``"s.subject_id"`` or a correlated
    sub-select) spliced verbatim into the SQL — it is router-authored, never
    client input.  ``type`` drives value coercion for filters (``int``/``float``/
    ``bool``/``str``) so e.g. ``id=eq.abc`` fails with a clean 400.
    """

    expr: str
    type: type = str


@dataclass(frozen=True)
class QuerySpec:
    """The per-resource allowlist + defaults a router passes to ``parse_query``."""

    columns: Mapping[str, Col]
    default_order: list[tuple[str, str]] = field(default_factory=list)
    default_select: list[str] | None = None  # None → all columns, in declared order
    default_limit: int = 50
    max_limit: int = 200
    # True → an over-max ?limit= is clamped to max_limit (PostgREST/Supabase
    # max-rows behavior, used by the reflected user-table API); False → 422.
    clamp_limit: bool = False
    # Grammar dialect. False (default, the hand-written memory routers): the
    # lenient pre-existing contract — filter values without a known operator
    # prefix are implicit-eq literals, quotes are literal characters, aliases
    # are spliced bare. True (the reflected user-table API): PostgREST
    # semantics — an operator prefix is REQUIRED (PostgREST has no implicit
    # eq, so a typo'd operator can never silently compile to a no-match
    # literal), quoted values/lists are unquoted with backslash escapes and
    # malformed quoting is a 400, and aliases are quoted (reflected column
    # names can be mixed-case or contain any character).
    strict: bool = False


@dataclass(frozen=True)
class ParsedQuery:
    """Assembled SQL fragments + bound params for a list query.

    The router splices these into its literal statement::

        SELECT {select_list} FROM … {where_sql} {order_sql} {limit_sql}

    passing ``where_params + limit_params`` (in that order) as the parameters.
    """

    select_list: str
    selected: list[str]
    where_sql: str
    where_clause: str  # conditions joined by AND, WITHOUT the "WHERE " prefix
    where_params: list
    order_sql: str
    limit_sql: str
    limit_params: list
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Operator tables
# ---------------------------------------------------------------------------

_SIMPLE_OPS: dict[str, str] = {
    "eq": "=",
    "neq": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "like": "LIKE",
    "ilike": "ILIKE",
    "match": "~",
    "imatch": "~*",
}

# Full-text-search operators → the tsquery constructor they map to.
_FTS_OPS: dict[str, str] = {
    "fts": "to_tsquery",
    "plfts": "plainto_tsquery",
    "phfts": "phraseto_tsquery",
    "wfts": "websearch_to_tsquery",
}

_IS_VALUES = {"null", "true", "false", "unknown"}

# Operators known to the grammar. In the lenient dialect, a value that does
# NOT begin with one of these (as ``op.value``) is treated as an implicit
# ``eq`` exact match — so bare legacy params (``?type=note``) and dotted
# literals (timestamps) still work. In the strict dialect an operator prefix
# is required, so an unknown/typo'd operator is a 400 instead of a literal
# that silently matches nothing (fatal on a DELETE, which would report
# success while deleting nothing).
_KNOWN_OPS = frozenset(_SIMPLE_OPS) | frozenset(_FTS_OPS) | {"in", "is"}
# Operators that only make sense on a text column (pattern / regex / full-text).
_TEXT_OPS = frozenset({"like", "ilike", "match", "imatch"}) | frozenset(_FTS_OPS)

_RESERVED_KEYS = frozenset({"select", "order", "limit", "offset", "or", "and"})

_LANG_RE = re.compile(r"^([a-z]+)\(([a-z_]+)\)$")
_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _bad(msg: str) -> APIError:
    return APIError("bad_request", msg, 400)


def _invalid(msg: str) -> APIError:
    """422 for well-formed grammar whose value is out of the allowed range/type
    (limit/offset) — matches the status the prior FastAPI ``Query`` validation used."""
    return APIError("validation_failed", msg, 422)


# ---------------------------------------------------------------------------
# Value coercion
# ---------------------------------------------------------------------------


def _coerce(api_name: str, col: Col, value: str):
    """Coerce a raw string to the column's Python type (for cleaner errors)."""
    t = col.type
    try:
        if t is int:
            return int(value)
        if t is float:
            return float(value)
        if t is bool:
            lv = value.lower()
            if lv in ("true", "t", "1"):
                return True
            if lv in ("false", "f", "0"):
                return False
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise _bad(f"Invalid value '{value}' for column '{api_name}'.") from exc
    return value


# ---------------------------------------------------------------------------
# Filter condition builder
# ---------------------------------------------------------------------------


def _parse_op(raw: str, strict: bool) -> tuple[bool, str, str | None, str]:
    """Split a raw filter value into ``(negate, op, lang, value)``.

    Recognized forms: ``op.value``, ``op(lang).value``, and ``not.<op>…``.

    Lenient dialect: a value that does NOT begin with a known operator token is
    an implicit ``eq`` (exact match) over the whole string — bare legacy params
    (``?type=note``) and dotted literals (e.g. timestamps) work unambiguously.

    Strict dialect: the operator prefix is required (as in PostgREST). Falling
    through to implicit-eq would turn any unknown/typo'd/unimplemented operator
    (``qe.x``, ``cs.{a}``) into a literal that silently matches nothing — on the
    generic write surface that reads as a successful DELETE of zero rows.
    """
    negate = False
    body = raw
    if body.startswith("not."):
        candidate = body[4:]
        tok = candidate.partition(".")[0]
        m = _LANG_RE.match(tok)
        base = m.group(1) if m else tok
        if base in _KNOWN_OPS:
            negate = True
            body = candidate

    op_tok, dot, value = body.partition(".")
    m = _LANG_RE.match(op_tok)
    base = m.group(1) if m else op_tok
    if dot and base in _KNOWN_OPS:
        if strict and m and base not in _FTS_OPS:
            # PostgREST's op(any)/op(all) modifiers — implemented only for the
            # FTS language form. Letting e.g. like(any).{a*,b*} through would
            # compile a literal LIKE '{a%,b%}' that silently matches nothing.
            # Lenient dialect: the modifier is parsed and ignored, as on main.
            raise _bad(f"Operator modifier '({m.group(2)})' is not supported for '{base}'.")
        lang = m.group(2) if m else None
        return negate, base, lang, value

    if strict:
        raise _bad(
            f"Expected '<operator>.<value>' with a supported operator "
            f"(eq, neq, gt, gte, lt, lte, like, ilike, match, imatch, in, is, "
            f"fts, plfts, phfts, wfts), got '{raw}'."
        )

    # No recognized operator prefix → implicit eq over the entire value.
    return negate, "eq", None, body


def _unquote_value(value: str) -> str:
    """Strip PostgREST double quotes (with backslash unescaping) from a fully
    quoted filter value — required inside or=()/and=() groups, where quoting is
    how values containing commas/spaces survive the group split."""
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return re.sub(r"\\(.)", r"\1", value[1:-1])
    return value


def _build_condition(
    api_name: str, col: Col, raw: str, *, strict: bool = False, in_group: bool = False
) -> tuple[str, list]:
    """Build one ``WHERE`` fragment + its params for ``col`` and a raw value.

    In the strict dialect, a quoted scalar value inside an or=()/and=() group
    (``in_group=True``) is unquoted the way PostgREST does; in the lenient
    dialect quotes are literal characters (the pre-existing contract). Top-level
    filter values are literal in both dialects."""
    negate, op, lang, value = _parse_op(raw, strict)
    if strict and in_group and op != "in":
        value = _unquote_value(value)

    if op in _TEXT_OPS and col.type is not str:
        raise _bad(f"Operator '{op}' requires a text column, but '{api_name}' is not text.")

    if op in _SIMPLE_OPS:
        if op in ("like", "ilike"):
            params: list = [value.replace("*", "%")]
        else:
            params = [_coerce(api_name, col, value)]
        frag = f"{col.expr} {_SIMPLE_OPS[op]} %s"

    elif op == "in":
        inner = value.strip()
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1]
        elif strict:
            # PostgREST requires the parenthesized form; a stray/missing paren
            # would otherwise become part of a literal that matches nothing.
            raise _bad(f"'in' filter for '{api_name}' must be a parenthesized list: in.(a,b,…).")
        if strict:
            items = split_quoted_list(inner)
        else:
            items = [x.strip() for x in inner.split(",") if x.strip() != ""]
        if not items:
            raise _bad(f"Empty 'in' list for column '{api_name}'.")
        params = [_coerce(api_name, col, x) for x in items]
        placeholders = ", ".join(["%s"] * len(params))
        frag = f"{col.expr} IN ({placeholders})"

    elif op == "is":
        kw = value.lower()
        if kw not in _IS_VALUES:
            raise _bad(f"'is' filter for '{api_name}' must be one of {sorted(_IS_VALUES)}.")
        params = []
        frag = f"{col.expr} IS {kw.upper()}"

    elif op in _FTS_OPS:
        fn = _FTS_OPS[op]
        if lang:
            params = [lang, lang, value]
            frag = f"to_tsvector(%s, {col.expr}) @@ {fn}(%s, %s)"
        else:
            params = [value]
            frag = f"to_tsvector({col.expr}) @@ {fn}(%s)"

    else:
        raise _bad(f"Unknown operator '{op}' for column '{api_name}'.")

    if negate:
        frag = f"NOT ({frag})"
    return frag, params


def split_quoted_list(raw: str) -> list[str]:
    """Split a PostgREST list (``a,b`` / ``"a,b","c"``), honoring double quotes
    and unquoting the items (PostgREST escaping: ``\\"`` and ``\\\\``).
    Malformed quoting — an unterminated quote, or text adjacent to a closing
    quote — is a 400: silently misparsing it would compile a filter against
    values the client never sent. Used for strict-dialect ``in.(…)`` values
    and, in the user-table router, ``?columns=``/``?on_conflict=`` names."""
    items: list[str] = []
    i, n = 0, len(raw)
    while i < n:
        while i < n and raw[i] == " ":
            i += 1
        if i >= n:
            break
        if raw[i] == '"':
            i += 1
            buf: list[str] = []
            while i < n and raw[i] != '"':
                if raw[i] == "\\" and i + 1 < n:
                    i += 1
                buf.append(raw[i])
                i += 1
            if i >= n:
                raise _bad("Unterminated quoted value in list.")
            i += 1  # closing quote
            while i < n and raw[i] == " ":
                i += 1
            if i < n and raw[i] != ",":
                raise _bad("Malformed list: unexpected text after a quoted value.")
            items.append("".join(buf))
        else:
            j = raw.find(",", i)
            if j == -1:
                j = n
            token = raw[i:j].strip()
            if '"' in token:
                raise _bad("Malformed list: quotes must wrap the whole value.")
            if token:
                items.append(token)
            i = j
        if i < n and raw[i] == ",":
            i += 1
    return items


def _split_top(s: str) -> list[str]:
    """Split on top-level commas, respecting parentheses (for ``or``/``and``
    groups in the lenient dialect, where quotes are literal characters)."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in s:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _split_top_quoted(s: str) -> list[str]:
    """Strict-dialect ``_split_top``: double-quoted values (with backslash
    escapes) may contain commas/parentheses; an unbalanced quote is a 400 —
    silently swallowing the separators would collapse the group's conditions."""
    parts: list[str] = []
    depth = 0
    in_quotes = False
    escaped = False
    buf: list[str] = []
    for ch in s:
        if escaped:
            buf.append(ch)
            escaped = False
        elif in_quotes and ch == "\\":
            buf.append(ch)
            escaped = True
        elif ch == '"':
            in_quotes = not in_quotes
            buf.append(ch)
        elif not in_quotes and ch == "(":
            depth += 1
            buf.append(ch)
        elif not in_quotes and ch == ")":
            depth -= 1
            buf.append(ch)
        elif not in_quotes and ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if in_quotes:
        raise _bad("Unbalanced quote in group.")
    if buf:
        parts.append("".join(buf))
    return parts


def _build_bool_group(raw: str, spec: QuerySpec, kw: str) -> tuple[str, list]:
    """Build a parenthesised ``(a <kw> b …)`` fragment from ``or=(…)`` / ``and=(…)``."""
    label = kw.lower()
    s = raw.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    conds = _split_top_quoted(s) if spec.strict else _split_top(s)
    parts: list[str] = []
    params: list = []
    for cond in conds:
        name, dot, rest = cond.strip().partition(".")
        if not dot:
            raise _bad(f"Malformed '{label}' condition '{cond}'.")
        col = spec.columns.get(name)
        if col is None:
            raise _bad(f"Unknown column '{name}' in '{label}' group.")
        frag, p = _build_condition(name, col, rest, strict=spec.strict, in_group=True)
        parts.append(frag)
        params.extend(p)
    if not parts:
        raise _bad(f"Empty '{label}' group.")
    return "(" + f" {kw} ".join(parts) + ")", params


def _build_or_group(raw: str, spec: QuerySpec) -> tuple[str, list]:
    return _build_bool_group(raw, spec, "OR")


def _build_and_group(raw: str, spec: QuerySpec) -> tuple[str, list]:
    return _build_bool_group(raw, spec, "AND")


# ---------------------------------------------------------------------------
# select / order / pagination builders
# ---------------------------------------------------------------------------


def quote_ident(name: str) -> str:
    """Double-quote a SQL identifier (doubling embedded quotes).

    Used for output aliases here and for reflected table/column identifiers in
    app/helpers/reflect.py. Spec column names may come from catalog reflection
    and can be mixed-case or contain any character; unquoted they would
    case-fold or be a syntax error. Quoting is a no-op for the lowercase
    identifiers the hand-written routers use.

    ``%`` is doubled for psycopg's client-side placeholder parser: the quoted
    identifier is spliced into SQL executed with bound params, where a lone
    ``%`` is a ProgrammingError."""
    return ('"' + name.replace('"', '""') + '"').replace("%", "%%")


def _alias_sql(name: str, spec: QuerySpec) -> str:
    """Render one output alias. Strict dialect: quoted — reflected column
    names can be mixed-case or contain any character, and quoting preserves
    the exact JSON key (PostgREST behavior). Lenient dialect: spliced bare,
    the pre-existing wire contract (Postgres case-folds unquoted aliases)."""
    return quote_ident(name) if spec.strict else name


def _build_select(value: str, spec: QuerySpec) -> tuple[str, list[str]]:
    pieces: list[str] = []
    selected: list[str] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if item == "*":
            # PostgREST wildcard — every spec column (supabase clients send
            # ?select=* by default).
            for name, col in spec.columns.items():
                pieces.append(f"{col.expr} AS {_alias_sql(name, spec)}")
                selected.append(name)
            continue
        if ":" in item:
            alias, name = item.split(":", 1)
        else:
            alias = name = item
        # A client-supplied name is spliced as the alias: in the lenient
        # dialect it goes in bare, so it must be a plain identifier; in the
        # strict dialect quoting makes any name safe, but a plain-form item
        # is already validated by the column lookup below.
        if (":" in item or not spec.strict) and not _IDENT_RE.match(alias):
            raise _bad(f"Invalid column alias '{alias}'.")
        col = spec.columns.get(name)
        if col is None:
            raise _bad(f"Unknown column '{name}' in select.")
        pieces.append(f"{col.expr} AS {_alias_sql(alias, spec)}")
        selected.append(alias)
    if not pieces:
        raise _bad("Empty select list.")
    return ", ".join(pieces), selected


def _default_select(spec: QuerySpec) -> tuple[str, list[str]]:
    names = spec.default_select if spec.default_select is not None else list(spec.columns.keys())
    pieces = [f"{spec.columns[n].expr} AS {_alias_sql(n, spec)}" for n in names]
    return ", ".join(pieces), list(names)


def _build_order(value: str, spec: QuerySpec) -> str:
    terms: list[str] = []
    for term in value.split(","):
        term = term.strip()
        if not term:
            continue
        parts = term.split(".")
        name = parts[0]
        col = spec.columns.get(name)
        if col is None:
            raise _bad(f"Unknown column '{name}' in order.")
        direction = "ASC"
        nulls = ""
        for mod in parts[1:]:
            ml = mod.lower()
            if ml == "asc":
                direction = "ASC"
            elif ml == "desc":
                direction = "DESC"
            elif ml == "nullsfirst":
                nulls = " NULLS FIRST"
            elif ml == "nullslast":
                nulls = " NULLS LAST"
            else:
                raise _bad(f"Invalid order modifier '{mod}' for '{name}'.")
        terms.append(f"{col.expr} {direction}{nulls}")
    if not terms:
        raise _bad("Empty order clause.")
    return "ORDER BY " + ", ".join(terms)


def _parse_int(value: str | None, default: int, name: str) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (ValueError, TypeError) as exc:
        raise _invalid(f"'{name}' must be an integer.") from exc


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_query(query_params, spec: QuerySpec, *, reserved: tuple[str, ...] = ()) -> ParsedQuery:
    """Parse PostgREST-style query params into SQL fragments against ``spec``.

    ``query_params`` is a Starlette ``QueryParams`` (``request.query_params``).
    ``reserved`` lists param keys the *caller* consumes itself (e.g. a legacy
    ``q`` shortcut) so they are not mistaken for column filters.
    """
    ignored = _RESERVED_KEYS | set(reserved)

    where_parts: list[str] = []
    where_params: list = []

    for key, raw in query_params.multi_items():
        if key in ignored:
            continue
        col = spec.columns.get(key)
        if col is None:
            # Unknown keys are ignored, not rejected — matches the prior lenient
            # contract (e.g. the ?debug=1 SQL trace, cache-busters, tracking params).
            continue
        frag, p = _build_condition(key, col, raw, strict=spec.strict)
        where_parts.append(frag)
        where_params.extend(p)

    for raw in query_params.getlist("or"):
        frag, p = _build_or_group(raw, spec)
        where_parts.append(frag)
        where_params.extend(p)

    for raw in query_params.getlist("and"):
        frag, p = _build_and_group(raw, spec)
        where_parts.append(frag)
        where_params.extend(p)

    where_clause = " AND ".join(where_parts)
    where_sql = ("WHERE " + where_clause) if where_parts else ""

    sel = query_params.get("select")
    if sel:
        select_list, selected = _build_select(sel, spec)
    else:
        select_list, selected = _default_select(spec)

    ordv = query_params.get("order")
    if ordv:
        order_sql = _build_order(ordv, spec)
    elif spec.default_order:
        terms = [f"{spec.columns[n].expr} {d.upper()}" for n, d in spec.default_order]
        order_sql = "ORDER BY " + ", ".join(terms)
    else:
        order_sql = ""

    limit = _parse_int(query_params.get("limit"), spec.default_limit, "limit")
    if limit < 0:
        raise _invalid("'limit' must be >= 0.")
    if limit > spec.max_limit:
        if not spec.clamp_limit:
            raise _invalid(f"'limit' must be <= {spec.max_limit}.")
        limit = spec.max_limit

    offset = _parse_int(query_params.get("offset"), 0, "offset")
    if offset < 0:
        raise _invalid("'offset' must be >= 0.")

    limit_sql = "LIMIT %s"
    limit_params: list = [limit]
    if offset:
        limit_sql += " OFFSET %s"
        limit_params.append(offset)

    return ParsedQuery(
        select_list=select_list,
        selected=selected,
        where_sql=where_sql,
        where_clause=where_clause,
        where_params=where_params,
        order_sql=order_sql,
        limit_sql=limit_sql,
        limit_params=limit_params,
        limit=limit,
        offset=offset,
    )


def build_where(*clauses: str) -> str:
    """Join non-empty condition fragments into a ``WHERE …`` clause (or "").

    Lets a handler merge the parser's ``where_clause`` with its own base/legacy
    conditions while keeping param order under the handler's control::

        where_sql = build_where(BASE, qp.where_clause, legacy_clause)
        params = qp.where_params + legacy_params  # same order as the clauses
    """
    real = [c for c in clauses if c]
    return ("WHERE " + " AND ".join(real)) if real else ""


# ---------------------------------------------------------------------------
# Counting + Content-Range (PostgREST-style pagination metadata)
# ---------------------------------------------------------------------------


def prefer_token(request, key: str, values: tuple[str, ...]) -> str | None:
    """Extract one ``key=value`` preference from the ``Prefer:`` header,
    where ``value`` must be one of ``values``. Shared by count/return/
    resolution parsing so the header grammar lives in one place. Word
    boundaries prevent substring misreads (``discount=exact``,
    ``return=minimalistic``)."""
    m = re.search(rf"\b{key}=({'|'.join(values)})\b", request.headers.get("prefer", ""))
    return m.group(1) if m else None


def wants_count(request) -> str | None:
    """Return the requested count strategy from a ``Prefer: count=…`` header.

    One of ``exact`` / ``planned`` / ``estimated``, or None when absent.
    """
    return prefer_token(request, "count", ("exact", "planned", "estimated"))


def content_range(offset: int, returned: int, total: int | None) -> str:
    """Build a ``Content-Range`` header value: ``<first>-<last>/<total|*>``.

    An empty page renders the range as ``*`` (e.g. ``*/0``); an unknown total
    (no count requested) renders as ``*`` (e.g. ``0-9/*``) — matching PostgREST.
    """
    span = f"{offset}-{offset + returned - 1}" if returned > 0 else "*"
    return f"{span}/{'*' if total is None else total}"


def resolve_total(conn, count_kind: str | None, from_sql: str, where_sql: str, where_params) -> int | None:
    """Compute the total matching row count for a list query, or None.

    ``exact`` runs ``COUNT(*)``; ``planned``/``estimated`` read the planner's
    row estimate via ``EXPLAIN`` (no execution). ``from_sql`` is the FROM body
    (e.g. ``"maludb_subject s"`` or a table + JOINs), ``where_sql`` the full
    ``WHERE …`` clause (or "") with its ``where_params`` — the same filtered set
    as the list query, so the count matches what a limit-less fetch would return.
    """
    if not count_kind:
        return None
    from app.database import db_one  # deferred import to avoid a module cycle

    if count_kind == "exact":
        row = db_one(conn, f"SELECT count(*) AS n FROM {from_sql} {where_sql}", where_params)
        return int(row["n"]) if row and row["n"] is not None else 0

    # planned / estimated → the planner's estimate (EXPLAIN does not execute).
    row = db_one(conn, f"EXPLAIN (FORMAT JSON) SELECT 1 FROM {from_sql} {where_sql}", where_params)
    plan = row["QUERY PLAN"]
    if isinstance(plan, str):
        plan = json.loads(plan)
    return int(plan[0]["Plan"]["Plan Rows"])
