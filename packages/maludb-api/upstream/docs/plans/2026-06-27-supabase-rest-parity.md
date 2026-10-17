# Supabase REST-API Parity Plan

**Date:** 2026-06-27
**Status:** Phase 0, Phase 1 (read-path + counts), and Phase 2 (bulk on facades) landed; RLS deferred. The 2026-07-01 scope pivot (user application tables via a generic reflective router) is **built** — see "2026-07-01 build" below.
**Author:** gap analysis + plan

## 2026-07-01 — Scope pivot: user application tables (handoff notes)

The user clarified the actual goal: MaluDB should be offerable as a **hosted
DBaaS like Supabase** — clients talk to their **own application tables** over
HTTP with no app server / SQL driver in between. The Supabase-parity surface is
**for user-created tables, NOT the memory structures**. The work below (Phases
0–2 on the memory routers) remains useful ergonomics but is not the target;
the next phase is a **generic, catalog-reflective table API** — the thing
direction C originally excluded. Direction C stays valid *for the memory
endpoints*; user tables by definition can't have hand-written routers.

### Analysis of maludb-core (/home/maludb/maludb-public, v0.100.0)

- **Multi-tenant-by-schema, one database.** Each tenant = a Postgres schema
  named after its owning role (`CREATE SCHEMA app AUTHORIZATION app`;
  `sql/role_onboarding.sql:89`). Tenant role search_path:
  `<tenant>, maludb_core, public` — matching what this server already sets
  (`app/database.py:89`).
- **Memory structures:** `maludb_core` schema holds ~157 `malu$*` storage
  tables (RLS `owner_schema = current_schema()`); `mc2db` holds the MCP
  registry; ~56 `maludb_*` facade **views** + ~20 facade functions are created
  *inside* each tenant schema by `maludb_core.enable_memory_schema()`.
- **User application tables live in the tenant's own schema** (e.g.
  `app.orders`), alongside the facades; optionally also in shared `public`
  (README.md:219, docs/admin-guide.md:40-52). No restriction stops the tenant
  role creating tables — it owns its schema.
- **Distinguishing user tables from memory structures is clean:**
  `information_schema.tables WHERE table_schema = current_schema() AND
  table_type = 'BASE TABLE' AND table_name NOT LIKE 'maludb\_%'`
  (facades are views; storage is in other schemas).
- **Tenant isolation needs no new RLS:** the API connects as the tenant role,
  which only owns its own schema. Per-end-user RLS stays deferred.

### Recommended architecture (not yet started)

New router (e.g. `app/routers/rest.py`) implementing the PostgREST surface
scoped to user tables:

1. **Table resolution & safety** — resolve `{table}` against
   `information_schema` for the tenant's own schema only; reject `maludb_*` /
   `malu$*`; identifiers come only from the catalog (quote via
   `psycopg.sql.Identifier`), never client input. Build a `QuerySpec` from
   reflected columns (type-mapped), cached per tenant+table with short TTL.
2. **Read path** — `GET /{table}` reusing `app/helpers/query.py::parse_query`
   wholesale (filter grammar, `select=`, `order=`, limit/offset,
   `Prefer: count=` + `Content-Range`). ~90% already built.
3. **Write path** — `POST` (single + bulk array, `?columns=`, `?on_conflict=`
   + `Prefer: resolution=merge-duplicates|ignore-duplicates` →
   `INSERT … ON CONFLICT`), filtered `PATCH`/`DELETE`,
   `Prefer: return=representation|minimal`. User tables have real PKs and
   sequences — no `MAX(id)+1` advisory-lock gymnastics needed.
4. **Later** — array/JSON operators (`cs/cd/ov`, `data->>f`), FK-reflected
   resource embedding, `/rpc/{function}`.

### Open decisions — ANSWERED by user 2026-07-01

1. **Wire compat: BOTH.** One implementation, two mounts — full PostgREST
   compat at `/rest/v1/{table}` (bare arrays, PostgREST error shape, supabase
   SDKs work unchanged) **and** house-style `/v1/tables/{table}` (envelopes,
   standard error shape).
2. **Prior memory-router parity work: keep**, exposed as-is.
3. **Table scope: tenant schema only** (base tables; `maludb_*`/`malu$*`
   rejected). `public` and user views excluded for now.

### 2026-07-01 build (branch `feat/rest-user-tables`)

Implemented per the architecture above:

- `app/helpers/reflect.py` — per-request catalog reflection (`resolve_table`):
  base tables in the tenant role's own schema only (scoped on `current_user` —
  see review fix #7 below), type-mapped columns, PK discovery,
  builds the `QuerySpec`. No cache — DDL is visible immediately.
- `app/routers/rest.py` — the generic router on both mounts. Read path reuses
  `parse_query` (+ new `select=*` wildcard support in `query.py`, which
  supabase clients send by default); counts + `Content-Range`; single-object
  `Accept: application/vnd.pgrst.object+json` (406 `PGRST116` mismatch). Write
  path: bulk insert (union-of-keys, missing → `DEFAULT`), `?columns=` (accepts
  PostgREST-quoted names — supabase-py sends `columns="a","b"`), upsert via
  `Prefer: resolution=` + `?on_conflict=` (default PK), filtered PATCH/DELETE,
  `Prefer: return=representation|minimal`. **Strict unknown-key rejection**
  (400) — deliberate divergence from the lenient memory routers, because an
  ignored typo'd filter on DELETE would nuke the table; `debug` stays allowed.
  PostgREST error bodies on `/rest/v1` (SQLSTATE as `code`; `PGRST205`/`204`/
  `116`/`100` for app errors); global house handlers on `/v1/tables`.
- Docs: `docs/rest-user-tables.md`.
- Tests: `tests/test_rest.py` (builders, strict keys, `select=*`, registration)
  + `tests/test_rest_e2e.py` — a real-DB end-to-end suite gated on
  `MALUDB_E2E_TOKEN`/`MALUDB_E2E_DSN` (closes the "e2e never exercised" gap).
- **Verified 2026-07-01 on this server** (local Postgres, maludb_core 0.100.0,
  tenant `app`): 459 unit tests + 12 e2e tests pass; the real `supabase-py`
  v2.31 client passes a full CRUD/upsert/count/single()/or_() script against
  `/rest/v1`, including PostgREST-shaped error surfacing (23505 → client
  `APIError.code`).

Known gaps (explicit 400s, documented): resource embedding, `/rpc`, JSON-path
and array operators, `Range` headers, CSV, `PUT` upsert. Auth failures use the
house error shape even on `/rest/v1` (dependency runs before the router).

### Code review of the generic router (high effort, 2026-07-01)

A workflow-backed review found 10 defects, all fixed the same day:
1. **?limit/?order silently dropped on PATCH/DELETE** → implemented PostgREST's
   limited update/delete (`WHERE ctid IN (SELECT ctid … ORDER … LIMIT …)`),
   triggered only by an explicit client `limit`/`offset`.
2. **.single() 406 after the write committed** (autocommit) → the write and the
   cardinality check now run in one transaction; mismatch rolls back.
3. **Unquoted SQL aliases** case-folded camelCase columns / syntax-errored on
   exotic names → all three select paths in `query.py` quote the alias.
4. **Lists always bound as Jsonb** broke `ARRAY` columns → `_adapt` binds by
   the column's reflected `data_type` (jsonb only for json/jsonb).
5. **numeric filters coerced through float** lost precision → numeric/real/
   double now pass through as text; Postgres compares at full precision.
6. **`?debug` collided with a tenant column named `debug`** → `debug` is
   reserved in every `parse_query` call on this surface.
7. **`current_schema()` scoping could resolve to a shared schema** for a role
   without its own schema → reflection scopes on `current_user` (the tenant
   schema is named after the role — the onboarding contract).
8. **JSONDecodeError → 500** on malformed bodies → `_read_json` maps any body
   parse failure to 400 (`PGRST102` on /rest/v1).
9. **PK reflection included INCLUDE columns** (poisoned default `on_conflict`)
   → pg_index walk limited to `indnkeyatts`.
10. **POST silently ignored filter params** → POST now rejects everything but
    `select`/`columns`/`on_conflict`/`debug`.

Re-verified after the fixes: 468 unit + 19 e2e tests green (new regression
tests cover every finding), supabase-py compat script passes.

### Second review round (high effort, 2026-07-01)

A second workflow review of the fixed branch found 10 more, all addressed:
1. Filter-shaped `?debug=eq.x` was silently dropped (unfiltering a write!) →
   now rejected with 400 unless the value is the documented `0`/`1`.
2. Offset-only writes dragged the default LIMIT 1000 into the ctid window →
   the window now uses only the client's explicit limit/offset.
3. Heterogeneous bulk merge-upserts overwrote unmentioned columns with
   DEFAULT → rejected (PostgREST's "all object keys must match").
4. `bytea` values crashed JSON serialization → returned as `\x…` hex.
5. Decimal responses lose precision through float → **documented divergence**
   (stdlib json cannot emit exact decimal digits; JS clients reparse to float
   regardless).
6. `?columns=`/`?on_conflict=` collided with same-named table columns in the
   RETURNING-select parse → reserved on the POST path.
7. Over-max `?limit=` returned 422, breaking supabase-js `.range()` →
   reflected specs clamp (`QuerySpec.clamp_limit`), matching max-rows.
8. Alias quoting changes `?select=Alias:col` casing on the pre-existing memory
   endpoints (was case-folded to lowercase) → **accepted intentionally**;
   PostgREST preserves alias case and reflected columns require quoting.
9. Quoted `?columns=` names containing commas mis-split → quote-aware
   tokenizer (`_split_columns`).
10. PK catalog query ran on every request → reflected lazily
    (`include_pk=True` on the insert path only).

Final state: 500 tests green (unit + 25 e2e regression tests), lint/format
clean on touched files, supabase-py compat script passes.

### Third review round (high effort, 2026-07-01)

Ten more findings, all addressed:
1. `in.()` did not unquote PostgREST-quoted values (supabase clients quote
   anything containing `, : ( )`) → shared `split_quoted_list` used for
   `in.()`, `?columns=`, `?on_conflict=` (also fixes quoted-comma names).
2. Write windows reused qp's clamped/defaulted limit (`?limit=5000` silently
   deleted 1000) → `_write_window` parses the raw explicit values; over-max on
   a write is a 400, empty values count as absent.
3. Repeated `?debug=eq.true&debug=1` bypassed the debug guard via last-value
   `get()` → every occurrence checked with `getlist`.
4. Unsupported PostgREST operators (`cs`/`cd`/`ov`/…) fell through to implicit
   eq (silently matching nothing) → explicit 400, including behind `not.`.
5. `%` in reflected identifiers broke psycopg placeholder parsing →
   `quote_ident` doubles `%`.
6. Alias-casing wire change on memory endpoints → **accepted** (PostgREST
   preserves alias case; grammar shipped days ago, no known consumers).
7. TracerMiddleware injected `meta` into bare-object responses and dropped
   headers on rebuild → `/rest/` exempted from debug injection; original
   headers now carried over on the house mounts.
8. Plan doc still said `current_schema()` in the build summary → corrected.
9. Prefer-header parsing duplicated across modules → shared
   `query.prefer_token` used by count/return/resolution.
10. Copy-pasted try/except on the four /rest handlers → left as-is
    (deliberate: explicit per-handler guard; a decorator adds indirection for
    four short handlers, and the sync/async split makes it uglier).

Final state: 508 tests green (incl. 28 real-DB e2e), lint/format clean,
supabase-py compat verified after each round.

### Fourth review round (high effort, 2026-07-02)

Ten findings, all addressed:
1. **Regression from round 3**: the unsupported-op probe fired on bare
   dot-less values (`?label=all` → 400 on every list endpoint) → the probe now
   requires the `op.value` shape.
2. Quoted values inside `or=()`/`and=()` bound their quotes literally →
   group conditions unquote (backslash unescape), and `_split_top` respects
   quotes so quoted commas survive the group split.
3. `op(any)`/`op(all)` modifier forms compiled to literal matches (silent
   no-op) → 400 for non-FTS parenthesized modifiers; `fts(lang)` unchanged.
4. `split_quoted_list` used CSV doubled-quote escaping; PostgREST uses
   backslashes → switched, plus whitespace tolerated before quoted tokens.
5. JSON scalars for json/jsonb columns bound as text/int (Postgres type
   error) → `_adapt` binds every non-NULL value as jsonb for JSON columns.
6. `bytea[]` crashed serialization → `_encode_rows` recurses into arrays.
7. HEAD ran the full data select → projects a constant (`SELECT 1`), keeping
   Content-Range/count semantics.
8. `_parse_window_int`'s int/negative validation was dead (parse_query runs
   first) → removed; only the over-max-on-writes 400 remains.
9. Debug-injection opt-out generalized to `/mcp` too (bare JSON-RPC bodies had
   the same phantom-`meta` corruption — pre-existing bug).
10. PK reflection on POST now runs only for upserts; `_run_write` dedupes the
    representation/exec block; `_quote_alias` alias removed.

Final state: 517 tests green (incl. 28 real-DB e2e), supabase-py compat
verified.

### Fifth review round (high effort, 2026-07-02) — the dialect split

Round 5 identified the structural root of the recurring findings: the shared
grammar was leaking PostgREST behavior changes into the pre-existing memory
endpoints (implicit-eq regressions, group unquoting, alias casing), while the
lenient implicit-eq leaked INTO the strict surface (typo'd operators silently
matching nothing). Fixed with an explicit dialect flag, `QuerySpec.strict`:

- **Lenient (default; all memory routers)** — byte-for-byte the main contract:
  implicit-eq fallback, quotes are literal characters, bare (case-folded)
  aliases, plain comma-split in `in.()` and groups. The round-2/3 divergences
  previously "accepted" on these endpoints are now simply gone.
- **Strict (reflected user tables)** — PostgREST semantics: operator prefix
  required (unknown/typo'd operator → 400, closing the whole silent-no-op
  class, not a hand-curated denylist), PostgREST quoting with backslash
  escapes in `in.()`/groups/`?columns=`, malformed or unbalanced quoting →
  400, quoted aliases (exact JSON key case).

Also from round 5: HEAD now runs a windowed count instead of fetching up to
1000 discarded rows (honest Content-Length 0 + correct Content-Range); the
four /rest handlers share one `_pgrst_route` decorator (wire-format guarantee
can't be forgotten on future routes); `AuthContext` annotations added per
CLAUDE.md. Final state: 520 tests green (incl. 30 real-DB e2e), supabase-py
compat verified.

### Sixth review round (high effort, 2026-07-02)

Five confirmed correctness bugs + cleanups, all addressed:
1. merge-duplicates homogeneity check fired even with `?columns=`, rejecting
   supabase-js bulk upserts (it always sends `?columns=` for arrays) → the
   check now applies only when `?columns=` is absent, matching PostgREST.
2. Strict `in.()` accepted a missing/unbalanced paren as part of the literal
   (silent no-match) → the parenthesized form is required, else 400.
3. The op(modifier) rejection ran in both dialects, narrowing the lenient
   contract (`eq(any).x` 400'd; main parsed-and-ignored it) → strict-only.
4. HEAD + `Accept: vnd.pgrst.object+json` always 406'd (cardinality check ran
   against the deliberately empty HEAD body) → skipped for HEAD.
5. `prefer_token` substring-matched (`Prefer: discount=exact` triggered a
   count) → word-boundary anchors.
Cleanups: all /rest handlers async (single-branch decorator), the RETURNING
parse skipped on minimal inserts, `TableInfo` collapsed to one column map,
`_GRAMMAR_KEYS` derived from the parser's reserved set, and CLAUDE.md amended
with the deliberate SQL-literality carve-out for the generic router.

Final state: 526 tests green (incl. 32 real-DB e2e), supabase-py compat
verified.

## Progress

- **Phase 0 — done.** `app/helpers/query.py` (`QuerySpec`/`Col`/`parse_query`/`build_where`) + unit tests in `tests/test_query.py`.
- **Phase 1 — done.**
  - *Filtering/select/order/pagination* across all list endpoints: `subjects, verbs, projects, pools, skills, notes, episodes, documents, attributes, statements`. Each declares a `QuerySpec` allowlist; the `SELECT … FROM` stays literal and only WHERE/ORDER/LIMIT/projection come from the parser. Fully back-compatible: legacy typed params (`q`, `type`, `kind`, `provenance`, `target_*`, `visibility`, `with`, …) are reserved and keep exact-match/substring semantics; new op-grammar filtering applies to non-legacy columns; default select/order reproduce the original responses exactly. Shape helpers (`shape_statement`/`shape_attribute`/`shape_episode`) guarded to tolerate `?select=` projections.
  - *Counts + `Content-Range`*: every list response sets `Content-Range: <first>-<last>/<total|*>`. `Prefer: count=exact` runs `COUNT(*)`; `planned`/`estimated` read the planner estimate via `EXPLAIN (FORMAT JSON)`. Helpers `wants_count`/`content_range`/`resolve_total` in `query.py`; `ParsedQuery` now exposes `limit`/`offset`.
- **Phase 2 — done for the graph facades and the entity tables.**
  - *Facade endpoints:* `POST /v1/statements` and `POST /v1/attributes` accept a single JSON object (unchanged) **or** a JSON array (bulk). A batch runs every item through the same idempotent facade in ONE transaction (all-or-nothing); response is `{"statements":[…]}` / `{"attributes":[…]}` for arrays, single object otherwise. Since those facades upsert on key, this delivers bulk insert **and** upsert.
  - *Entity tables (`MAX(id)+1`):* `POST /v1/subjects`, `POST /v1/verbs`, `POST /v1/projects` accept a JSON array too. Id generation is serialized with a per-**table** `pg_advisory_xact_lock` (via `tx_with_advisory_lock`) so concurrent inserters can't collide — the whole batch (and now single inserts too) is atomic. `subjects` and `projects` share the `maludb_subject` lock since both insert into that table. Chosen 2026-07-01 (advisory-lock option).
  - Shared helpers: `app/helpers/writes.py` (`as_items`, `tx_with_advisory_lock`) + `tests/test_writes.py`.
  - **Not done:** bulk for `pools`/`notes`/`episodes` (sequence/register-facade inserts — extendable, lower priority), and `on_conflict`-style client-chosen upsert targets. `documents` (multipart) and `skills` (bundle) are not JSON-array shaped.
- **Deferred by user (2026-06-30):** RLS (Phase 3) out of scope short-term — "bypass RLS entirely and focus on the core endpoints." Connection-level tenancy remains the only authorization.
- **Not yet started:** Phase 4 (docs of the grammar / OpenAPI enrichment); bulk for the non-facade write endpoints (see above).

## Code review (high effort, 2026-07-01)
A workflow-backed review found 6 correctness defects, all fixed:
1. **Reserved legacy columns shadowed the op grammar** — columns that were both in a `QuerySpec` and in `reserved=` fell to the legacy exact-match loop, so `?provenance=eq.accepted` returned 0 rows (or 422 on int columns). Fixed by deleting the legacy loops; those columns are now ordinary spec columns.
2. **Unknown query keys returned 400** — broke the documented `?debug=1` trace and any extra param. Fixed: `parse_query` now **ignores** unknown keys (prior lenient contract).
3. **Text-search ops on numeric/bool columns leaked a 500** — fixed with a type guard (`_TEXT_OPS` require `col.type is str` → 400).
4. **Top-level `and=(…)` was silently dropped** — now parsed like `or=(…)`.
5. **`/v1/skills` text-search ignored `offset`** (duplicate pages) — now rejects `offset` on that branch.
6. **`limit` over-max was silently clamped** (was 422) — now rejects with 422; limit/offset parse errors are 422 `validation_failed` again.

Enabling #1+#2 required the parser to accept a **bare value as implicit `eq`** (so `?type=note` still works while `?type=neq.x` also works). One finding (match/imatch regex → 500) was refuted (SQLSTATE class 22 already maps to 422).

## Verification (as of 2026-07-01)
428 tests pass (`pytest`), `ruff check app/ tests/` clean, app builds. Diff is functional-only (no formatting churn on unrelated files). Query + bulk paths are verified by unit tests; **end-to-end against a real tenant DB is still not exercised** by the suite (recommended before merge).

## Goal

Give MaluDB API users the day-to-day ergonomics of Supabase's auto-generated
table API (rich filtering, column selection, ordering, pagination + counts,
bulk insert, upsert) **without** abandoning this codebase's design principles
(SQL traceability, one router per domain, no generic CRUD base). Pair that with
**Postgres Row Level Security** so the richer read/write surface is safe at the
row level, not just the connection level.

## Decisions (locked)

| Question | Decision | Implication |
|----------|----------|-------------|
| Direction | **C — Extend existing per-domain routers** | Add a PostgREST-compatible query grammar *inside* the existing handlers via a shared parser + per-router column allowlists. No schema reflection, no generic `/{table}` routing. |
| Authorization | **Adopt Postgres RLS** | Move from connection-level tenancy only → per-row policies keyed on a request-scoped identity injected from `AuthContext`. |
| Scope | **REST API only** | In: CRUD + querying parity. Out: Realtime, TypeScript codegen, Storage, Auth-as-a-service. |

### Explicitly NOT in scope (parity we are choosing to forgo under direction C)

- Generic schema reflection / instant API for *arbitrary* new tables.
- PostgREST resource embedding grammar (`?select=*,author(*)`, `!inner`, spread `...`). Existing hand-coded embeds (`verbs[]`, `?with=attributes`) stay as-is.
- Generic `/rpc/{function}`. Functions remain behind named handlers + the MCP tools.
- JSON-path filtering/ordering (`data->>field`) — possible later stretch goal.
- Auto-generated client TypeScript types and the self-documenting dashboard.

## Gap analysis (where we are vs. Supabase / PostgREST)

Current state confirmed against the codebase (`app/routers/*`, `app/database.py`,
`app/auth.py`). The server is a curated, hand-written contract API — the
structural opposite of PostgREST's schema-reflective auto-API.

| # | Supabase / PostgREST capability | Today | Gap | In this plan? |
|---|---|---|---|---|
| 1 | Auto CRUD for every table/view | Hand-written per-domain routes only | Total | No (direction C) |
| 2 | Horizontal filtering `?col=eq.x` (eq/neq/gt/gte/lt/lte/like/ilike/in/is/cs/cd/ov/fts/match…) | Fixed `Query()` params → hardcoded columns; ad-hoc `ILIKE` | Large | **Yes — Phase 1** |
| 3 | Logical `and`/`or`/`not`, nestable | Implicit AND of whitelisted scalars | Large | **Yes — Phase 1** |
| 4 | Vertical filtering `?select=`, rename, cast | Fixed SELECT lists, baked aliases | Large | **Yes — Phase 1** |
| 5 | JSON/composite access in select/filter/order | None | Full | Stretch |
| 6 | Ordering `?order=col.desc.nullslast`, multi-key | `ORDER BY` hardcoded | Large | **Yes — Phase 1** |
| 7 | Pagination + counts (`limit`/`offset`, `Range`, `Content-Range`, `Prefer: count=`) | `limit` everywhere; one `offset`; no count envelope | Moderate | **Yes — Phase 1** |
| 8 | Bulk insert (JSON array / CSV), `?columns=` | Single-row inserts; replace-set loops in Python | Large | **Yes — Phase 2** |
| 9 | Upsert (`Prefer: resolution=merge-duplicates`, `?on_conflict=`, PUT) | `ON CONFLICT` only in SQLite auth store; PG upserts hidden in facades | Large at API layer | **Yes — Phase 2** |
| 10 | Resource embedding (joins) `?select=*,rel(*)` | Hand-coded fixed embeds | Large | No |
| 11 | Generic RPC `/rpc/{fn}` | Named handlers + 8 MCP tools | Large | No |
| 12 | Full-text search `fts/plfts/phfts/wfts` | `ILIKE` substring + dedicated vector endpoints | Moderate | Partial (Phase 1 `fts` operator if column has tsvector) |
| 13 | **RLS** — per-row policies on JWT claims (`auth.uid()`) | Connection-level tenancy; `role` carried but unused per-row | Architectural | **Yes — Phase 3** |
| 14 | API keys + JWT (anon/service_role) | `Bearer malu_…` → sha256 → SQLite → PG creds | Different model | Keep current model; extend with identity GUC |
| 15 | Self-documenting / introspection / OpenAPI reflects schema | Default FastAPI `/openapi.json` reflects routes only; sparse (raw `request.json()`) | Large | Partial (Phase 4 docs of the grammar) |
| 16 | TS type generation | None | Full | No |
| 17 | Realtime | None | Full | No |

## Design — preserving SQL traceability under direction C

The principle in `CLAUDE.md` ("Every SQL query is a literal string in the route
handler… no query builder") is preserved by keeping the **`SELECT … FROM …`
literal in each handler** and only assembling the **`WHERE` / `ORDER BY` /
`LIMIT`/`OFFSET` tail** from a *declared, per-router allowlist*. This is the same
structural-dynamic-SQL technique already used today (e.g. the `clauses`/`params`
build in `statements.py`, the `SET {', '.join(fields)}` in `subjects.py`), just
generalized and made PostgREST-compatible. **Client input never becomes a SQL
identifier** — column names are resolved through the allowlist map or rejected.

### Shared helper: `app/helpers/query.py`

A small, dependency-free parser. It does **not** know about any table; each
router passes it a spec.

```python
# Per-resource spec declared at the top of each router (DB column ↔ API field).
SUBJECT_QUERY = QuerySpec(
    table_alias="s",
    columns={                      # API name -> (db expression, type)
        "id":    Col("s.subject_id", int),
        "label": Col("s.canonical_name", str),
        "type":  Col("s.subject_type", str),
        "description": Col("s.description", str),
    },
    default_order=[("label", "asc")],
    max_limit=200,
)

# In the handler — SELECT/FROM stay literal; only the tail is assembled.
qp = parse_query(request.query_params, SUBJECT_QUERY)   # -> where_sql, params, order_sql, limit_sql, selected_cols
sql = f"""SELECT {qp.select_list}
            FROM maludb_subject s
           {qp.where_sql}
           {qp.order_sql}
           {qp.limit_sql}"""
rows = db_query(auth.conn, sql, qp.params)
```

`parse_query` responsibilities:

- **Filters:** parse `?col=op.value`; map `op` ∈ {eq,neq,gt,gte,lt,lte,like,ilike,in,is,cs,cd,ov,match,imatch,fts} to SQL operators; values always bound as `%s` params. Reject unknown columns/operators with `422 validation_failed` (matches existing error contract).
- **Logical:** `or=(a.eq.1,b.gt.2)` and `not.` prefix → parenthesized fragments.
- **Select:** `?select=id,label` validated against `columns`; supports `alias:col`. Default = all spec columns. (Casting deferred.)
- **Order:** `?order=label.desc.nullslast,id.asc` validated against `columns`.
- **Pagination:** `limit`/`offset` (and `Range` header later); clamp to `max_limit`.
- Returns fragments + the ordered param list; **never** returns raw identifiers from user input.

### Counts / `Content-Range`

Add an opt-in `Prefer: count=exact|planned|estimated` path. When present, the
handler runs a `count(*)` (exact) or reads `EXPLAIN`-derived estimate, and the
response sets `Content-Range: <from>-<to>/<total>`. Without the header, behavior
is unchanged (`Content-Range: <from>-<to>/*`). Implemented as a thin helper so
each list endpoint opts in with one line.

## Phased plan

### Phase 0 — Foundations (no behavior change)
- Add `app/helpers/query.py` (`QuerySpec`, `Col`, `parse_query`) + unit tests covering operator mapping, allowlist rejection, injection attempts, OR/NOT nesting, order/limit clamping.
- Add a `content_range()` response helper.
- Document the supported operator grammar in `docs/`.

### Phase 1 — Read-path parity (reference impl first, then fan out)
- Retrofit **`subjects.py` `list_subjects`** (`app/routers/subjects.py:153`) as the reference: keep the literal `SELECT … FROM maludb_subject s` + subquery counts, route filtering/select/order/pagination through `parse_query`. Preserve the existing `q` shortcut and `?with=attributes` as-is (back-compat).
- Add `Prefer: count=` + `Content-Range`.
- Fan out to the other list endpoints (`verbs`, `projects`, `pools`, `skills`, `notes`, `episodes`, `statements`, `documents`, `attributes`), each declaring its own `QuerySpec`. Keep every existing query param working (additive only).
- **Back-compat rule:** all changes are additive. Existing clients that send no new params get identical responses (same JSON envelope, same default ordering).

### Phase 2 — Write-path parity
- **Bulk insert:** accept a JSON array body on `POST` collection endpoints; iterate or multi-VALUES within the existing single-row SQL pattern (respecting the `MAX(id)+1` id-derivation where applicable — note this needs a guarded transaction to avoid id races under concurrency; document the locking choice).
- **Upsert:** support `Prefer: resolution=merge-duplicates` + `?on_conflict=` on collection `POST`, mapping to `INSERT … ON CONFLICT (…) DO UPDATE`. Only on tables with a real unique key (not the `MAX(id)+1` views — call out which resources qualify).
- **`Prefer: return=representation`** to echo created/updated rows; `?columns=` to restrict inserted columns.

### Phase 3 — Row Level Security (the architectural change)
This is staged carefully because of an ownership subtlety:

- **Ownership/bypass problem:** the tenant connects **as its own role, and its schema is named after that role** (`app/database.py:73-90`), so that role almost certainly *owns* its tables/views → **owners bypass RLS**. Two options:
  1. `ALTER TABLE … ENABLE ROW LEVEL SECURITY; ALTER TABLE … FORCE ROW LEVEL SECURITY;` so even the owner is subject to policy, **or**
  2. Introduce a **separate non-owner application role** per tenant that the API connects as (token → app role, not owner role). Cleaner long-term; bigger migration.
  Recommend (1) first (smaller blast radius), revisit (2) if policies get complex.
- **Request identity injection:** right after connect (alongside the existing `SET search_path`), set a request-scoped GUC from `AuthContext`, e.g. `SET maludb.user_id = %s` / `SET maludb.role = %s`. Connections are per-request and closed in the auth dependency `finally`, so a plain `SET` is safe; `db_tx_core` can additionally `SET LOCAL` for transaction scope. Policies read `current_setting('maludb.user_id', true)`.
- **Policies:** author RLS policies on tenant tables/facade base tables keyed on `maludb.user_id` (and/or `maludb.role`). Note the facades are **updatable VIEWS** (`maludb_subject`/`maludb_verb`) — confirm whether RLS must live on the base tables behind the views and how the views' triggers interact with policy.
- **Tests:** prove that two users in the same tenant see only their permitted rows on read, and are blocked on write, across the new generic query surface.
- **Caveat to surface:** until Phase 3 lands, the richer Phase 1/2 read/write surface is only as safe as the connection-level tenancy (whole-tenant scope). Sequence Phase 3 before exposing the broad surface to multi-user tenants, or gate Phase 1/2 behind a flag until RLS is in place.

### Phase 4 — Documentation / discoverability
- Document the operator grammar, `Prefer` headers, and `Content-Range` contract.
- Optionally enrich OpenAPI for the retrofitted endpoints (response models) so `/docs` is less sparse. (Full schema-reflective self-documentation remains out of scope.)

## Risks & open questions

1. **`MAX(id)+1` id derivation** (no sequences on `subject_id`/`verb_id`) makes bulk insert + concurrency tricky — needs an explicit locking/serialization decision in Phase 2.
2. **RLS on updatable views** — must confirm whether to apply policies on base tables vs. the facade views, and trigger interaction. Needs a spike against `maludb_core`.
3. **Owner-bypass** — decide FORCE-RLS vs. separate app role before writing policies.
4. **Error-contract fidelity** — new parse failures must map to the existing `{"error": {"code","message"}}` 422 shape, not FastAPI's default 422.
5. **`Range` header vs `limit/offset`** — support both or just query params first? (Lean: query params first, `Range` later.)
6. **Scope creep toward generic reflection** — direction C deliberately stops short; revisit only if per-router allowlists become unmaintainable.

## Reference: PostgREST behaviors we are matching (subset)

- Filters: `?col=op.value`; operators eq/neq/gt/gte/lt/lte/like/ilike/in/is/cs/cd/ov/match/imatch/fts(plfts/phfts/wfts).
- Logic: `or=(…)`, `and` implicit, `not.` prefix; `any`/`all` modifiers (later).
- Select: `?select=col,alias:col` (cast `::type` later).
- Order: `?order=col.dir[.nullsfirst|.nullslast]`, multi-key.
- Pagination: `limit`/`offset`; `Content-Range`; `Prefer: count=exact|planned|estimated`.
- Writes: bulk JSON array; `Prefer: resolution=merge-duplicates` + `on_conflict`; `Prefer: return=representation`; `?columns=`.
