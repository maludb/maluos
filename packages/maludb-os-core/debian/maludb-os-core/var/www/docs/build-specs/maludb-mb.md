# MaluDB MB — extension 0.106.0: the engine learns who is asking

Stage **MB** of `docs/hermes-integration-plan.md`. Written 2026-09-19 after reading
`maludb_core` 0.105.3 (line numbers below are in `sql/extension/maludb_core--0.105.3.sql`).
The work is in `github.com/maludb/maludb-core` (branch `phase-mb/principal-scoping`), with a small
companion change to `maludb-python-api-server`. **Nothing here touches the platform's schema,
tool surface or manifest** — the platform switching to engine-enforced scopes is a later stage
and goes through the checkpoint gate on its own.

## What the engine is today (facts, not the plan's assumptions)

1. **One tenancy axis.** Every memory table's policy is `owner_schema = current_schema()`.
   Inside a tenant there is no principal, no scope and no sensitivity filter anywhere on the
   retrieval path. `sensitivity` is stored on source packages, memories, episodes and chat
   messages and filtered on nowhere.
2. **`namespace` exists only on the vector layer** (`malu$vector_subject/verb/compartment`);
   chunks inherit it through their compartment. Documents, statements, episodes, memories and
   chat sessions carry none. The four vector tables have **no RLS**; their tenancy is procedural,
   inside SECURITY DEFINER workers.
3. **`malu$account` and `malu$partition` are cluster-wide** (globally unique names, not
   row-filtered, writable only by `maludb_llm_admin`; `malu$partition` is referenced by nothing).
   The plan said "agents/people map to `malu$account`, departments to `malu$partition`" — that
   would put one tenant's staff list in every tenant's view. **Changed:** principals and their
   scope grants are new *tenant-scoped* tables.
4. **Tombstones are honoured only on the ANN path.** `exact_vector_search_sql` filters
   `malu$vector_tombstone` in its `local_ann` branch (7524–7549); the `exact` branch is the C
   function `maludb_exact_vector_search_c` (`src/maludb_search.c:207`) and `exact_parallel` is
   `exact_vector_search_parallel_c` (7018) — neither mentions tombstones. Nothing anywhere deletes
   a document's chunks, `malu$vector_chunk.document_id` is a soft reference, and
   `tombstone_vector_chunk` has no caller and no tenant facade. That is the "deleted memory stays
   recallable" defect found on 2026-09-19.
5. **Episodes are already embeddable** (0.94/0.95): an episode mints an *event subject* whose card
   carries the title, the summary and the time, and a trigger marks that subject dirty. M4b as
   the plan wrote it ("add an episode card renderer") would embed everything twice. What is
   actually missing is (a) scope on the way out of `semantic_search`, and (b) on this server
   nothing drains the queue: `maludb_os_memory` has 3,042 dirty rows and 0 object embeddings.
   (b) is operations, not extension work — see "Not in this release".
6. **Skills**: `enabled` is the only gate; `malu$skill_access` grants to a *Postgres role*; nothing
   records a load. `_register_agent_skill_for_schema` already takes `p_enabled` — the window the
   platform complained about ("enabled for an instant") is the API not passing it.
7. **Pools**: `presence_update/leave/list/sweep` have no tenant facade (a tenant can read
   `maludb_pool_presence` and nothing else); `presence_list` does not return the cursor;
   `malu$active_memory_pool_access` is consulted by no function.

## Design

### One rule: everything carries a scope, a principal holds scopes

A **scope** is a namespace string — the same strings the platform already uses (`agent:44`,
`dept:3`, `org`, `default`). No new vocabulary: the vector layer's `namespace` *is* the scope of a
chunk. Rows that predate this release, and rows written with no scope, read as `'default'`.

**`malu$principal`** — `principal_id`, `owner_schema`, `principal_ref text` (the host's name,
`agent:44` / `member:1`; same pattern the API's profile routes accept), `principal_kind`
(`human` | `agent` | `service`), `display_name`, `home_scope text` (where this principal's own
writes land when it names none — `agent:44`), `max_sensitivity` (default `internal`), `enabled`,
timestamps; `UNIQUE (owner_schema, principal_ref)`.

**`malu$principal_scope`** — `owner_schema`, `principal_id`, `scope text`, `access_level`
(`read` | `write`; write implies read), `granted_at`, `revoked_at`; one live row per
(principal, scope, level). A principal always holds `write` on its `home_scope` implicitly.

**The session says who is asking** — three transaction-local settings, the pattern
`maludb_core.current_account_id` already established:

| Setting | Meaning |
|---|---|
| `maludb_core.principal_ref` | who. Empty / unset = **unrestricted**: exactly today's behaviour |
| `maludb_core.principal_scopes` | optional JSON array; **narrows** the stored grants, never widens |
| `maludb_core.principal_readonly` | `on` = refuse every scoped write |

Effective read scopes = stored grants ∩ session scopes (when given). So a stale stored grant
cannot outlive what the host computed live, and a confused host cannot widen past what the
engine was told. A principal that is set but unknown or disabled gets **nothing** (fail closed).

Trust boundary, stated plainly: a client holding the tenant's Postgres login can set these
settings itself — it is the tenant, and tenant-wide by definition. The settings bind callers who
reach the engine *through the API* with a principal-bound token (M2, API side). Same model as
`current_account_id`.

### Where it is enforced

| Surface | How |
|---|---|
| `malu$document`, `malu$episode_object`, `malu$memory`, `malu$chat_session`, `malu$active_memory_pool` | new columns `principal_ref text`, `scope text`; a **RESTRICTIVE** policy `principal_scope` beside `tenant_owner`: unrestricted session → true; else `COALESCE(scope,'default')` readable and `sensitivity` ≤ the principal's ceiling (documents take theirs from the source package; pools have none). INSERT/UPDATE need write on the scope. `BEFORE INSERT` stamps `principal_ref` and defaults `scope` to `home_scope`. |
| `malu$chat_message` | restrictive policy through its session + own `sensitivity` |
| `_memory_search_for_schema`, `vector_search_by_tags` (SECURITY DEFINER, bypass RLS) | namespace must be readable → else `insufficient_privilege`; hits whose document is above the ceiling are dropped |
| `_memory_ingest_edge_for_schema`, `_memory_request_extraction_for_schema` | namespace must be writable |
| `_note_search_for_schema` | document scope + sensitivity predicate |
| `semantic_search` (INVOKER) | an event subject is returned only if its episode is visible; statement/subject cards are tenant-shared vocabulary and stay visible (names, not content — recorded as a known limit) |
| `_memory_ingest_extraction_for_schema` | **M-fix′**: gains `p_namespace`; stamps it as the scope of the episodes it mints and of the source document; requires write |

`tenant_owner` stays byte-identical (`scripts/maludb-force-rls` keys on its name); the new policy
is `AS RESTRICTIVE`, because a second permissive policy would *widen* access.

### Forgetting (the defect)

- `exact` and `exact_parallel` filter tombstones (C query + the parallel wrapper). The `.so` is
  shared by every installed version; the new predicate needs the tombstone table, which every database since
  0.14.0 has (checked in the upgrade chain), so older databases on the same host keep working.
- `maludb_forget_document(p_document_id)` (tenant facade): deletes the document's chunks — and the
  chunks of its statements — marks touched ANN indexes stale, deletes the document→subject
  statements, the document and its source package (unless legal hold → refuse), returns counts.
  Hard delete of chunk rows is safe: the ANN branch inner-joins `malu$vector_chunk`, and
  `malu$ann_delta` / `malu$vector_tombstone` cascade.
- `maludb_forget_chunk(p_chunk_id)` for the orphan left on this server.
- Trigger: deleting a `malu$document` row deletes its chunks, so the old API path stops orphaning.

### Skills (M8b)

- `malu$skill_package` + `review_state` (`approved` default — existing rows stay approved —
  `proposed`, `rejected`), `proposed_by_principal`, `reviewed_by`, `reviewed_at`, `review_note`.
  `_skill_is_visible` additionally requires `review_state = 'approved'`. Lifecycle columns, so the
  content guard leaves them writable. `maludb_skill_register` gains `p_review_state`,
  `p_proposed_by`; `maludb_skill_review(skill_id, decision, note)` decides.
- `malu$skill_access.grantee_principal text` (role becomes nullable; exactly one of the two);
  visibility consults the session principal.
- `malu$skill_load_event` (`skill_id`, `bundle_hash`, `principal_ref`, `run_ref`, `loaded_at`) +
  `maludb_skill_record_load(...)` + view `maludb_skill_load_event`.

### Pools (M11)

Tenant facades `maludb_presence_update / _leave / _list` (list now returns `cursor_jsonb` and
`ttl_seconds`); `participant_ref` defaults to the session principal; a pool's `scope` decides who
may see and join it (the policy above). The role-based `malu$active_memory_pool_access` is left
as it is — unenforced and unused; principals use scopes.

### Principal facades

`maludb_principal_upsert`, `maludb_principal_grant_scope`, `maludb_principal_revoke_scope`,
views `maludb_principal`, `maludb_principal_scope`, and `maludb_principal_whoami()` (ref, kind,
effective read/write scopes, ceiling — what a caller is actually allowed, for the platform's
verify scripts). All in builder `_enable_memory_schema_01060_facade`; **`enable_memory_schema`
must be re-run per tenant after the upgrade.**

## Repo conventions this release must satisfy

Upgrade script `maludb_core--0.105.3--0.106.0.sql` + full script by concatenation; `DATA`,
`REGRESS`, control, `expected/load.out`; every new table registered for
`pg_extension_config_dump` and the sequence block re-run (`dump_registration`: 152 → +3); every
new FK indexed (`fk_index_coverage`); `COLLATE "default"` on text compared to indexed text inside
any function taking a `name` (`collation_index_use`); DCO sign-off; CHANGELOG + user manual.
New regress tests: `principal_scoping`, `vector_forget`, `skill_review_load`, `pool_presence_facade`.

## API companion (maludb-python-api-server, separate PR)

Per-request `SET LOCAL` of the three settings from `X-MaluDB-Principal` / `-Scopes` headers
(tenant token only — a delegated M2 token will carry them itself and ignore the headers);
`DELETE /v1/documents/{id}` → `maludb_forget_document`; `enabled` + `review_state` on skills
ingest; `POST /v1/skills/{id}/loads`; presence routes; principal routes; `/v1/memory/ingest`
passes the namespace and drops the `namespace_applied: false` warning when the engine is ≥ 0.106.

## Acceptance

1. No principal set → every existing regress test passes unchanged (95/95).
2. Principal `agent:44` with `agent:44` + `dept:3`: searching `dept:4` raises; a `dept:4` document,
   episode, chat session and pool are invisible; a `restricted` document in `dept:3` is invisible
   until the ceiling is raised; session scopes narrow and never widen; unknown/disabled principal
   sees nothing; `principal_readonly` refuses a write.
3. A forgotten document is gone from `exact`, `exact_parallel` and `local_ann` compartments; a
   tombstoned chunk is gone from all three.
4. A `proposed` skill resolves for nobody; approving makes it visible; a principal grant admits
   that principal only; a load is recorded with hash and run.
5. Presence join / heartbeat / leave through the tenant facades; a pool outside scope refuses.
6. Upgrade path 0.105.3 → 0.106.0 on a copy of a real tenant (`maludb_ma_scratch`) and fresh
   install both pass; `enable_memory_schema` re-run reports more objects than before.

## Built *(2026-09-19)* — acceptance as run

**State 2026-09-19 23:55 UTC: deployed.** Both PRs are merged (maludb/maludb-core#37 → 71cf34d,
maludb/maludb-python-api-server#16 → f8f1c94). API 0.3.0 went live at 23:01 against the old engine; the
extension was installed and all three databases on this server upgraded at 23:55, `maludb_os_memory` in 0.25 s
with every row count unchanged. The as-deployed record is at the foot of `docs/hermes-integration-plan.md`.
Branches (now merged):
`maludb-core` `phase-mb/principal-scoping` (9c3b044, worktree `/home/maludb/maludb-core-mb`) and
`maludb-python-api-server` `feat/principal-scoping-mb` (6404e4a, rebased on PR #15, worktree `/home/maludb/maludb-api-mb`).

| # | Result |
|---|---|
| 1 | All 100 existing regress tests pass with no principal set. Ten expected files changed, and only in version strings, object counts (165 → 194 facades, 152 → 156 registered tables, 230 → 233 foreign keys — all indexed) and one function signature in an error context. |
| 2 | `principal_scoping`: Sasha (`agent:44`; reads `dept:3` and `org`) sees 2 of 5 documents, 2 sources, 1 of 2 episodes, her own chat session and its message, 1 of 2 pools, her own memory. Searching `dept:4` **raises** rather than returning nothing; the `restricted` document in `dept:3` is dropped from search and invisible until the ceiling allows it (the owner sees it). Her header list narrows to one scope, cannot widen to `dept:4`, and an unreadable list reads nothing. Read-only refuses a write in her own scope. Unknown and disabled principals count zero everywhere. Read access is not write access on five different write paths. She cannot grant herself a scope or raise her own ceiling. A row she inserts claiming to be `member:1` is stamped `agent:44`. Another tenant's role asking about this schema gets an empty list. |
| 3 | `vector_forget`: one tombstoned chunk is gone from `exact` (the C scan), `exact_parallel` and `local_ann`. `maludb_forget_document` → `{"chunks": 1, "statements": 1, "source_package": "deleted"}`, `vector_count` true, ANN index marked stale; a held source refuses; the *old* way of deleting a document leaves no orphan chunk. |
| 4 | `skill_review_load`: Sasha's revision is `enabled` **and** resolves for nobody, herself and the tenant included; v1 stays live; she cannot approve it through the function, through the view, or by someone saying her name; approved and reserved for her, Seamus still resolves only v1 and cannot record a load of it; loads carry name, version, hash, principal and run, and survive the skill's deletion. |
| 5 | `pool_presence_facade`: join / heartbeat / cursor / leave by pool name; the roster returns cursor and TTL; Sasha is present as `agent:44` though she claimed to be `member:1`; for Seamus the pool does not exist. |
| 6 | Fresh install and the 0.105.3 → 0.106.0 path both pass. On a copy of **`maludb_os_memory`** (3,090 episodes, 19 documents): upgrade **0.2 s**, facades keep answering before the re-run, `enable_memory_schema` 0.5 s (194 objects); the backfill scoped the three namespaced documents (`agent:44`, `dept:3`, `dept:4`); bound as `agent:44` with a `dept:3` grant the real tenant role saw exactly 2 of 19 documents and 0 of 3,090 episodes, the episode scan taking 8 ms. The copy was dropped afterwards. |
| API | 40 unit + 15 e2e tests through the real app against a 0.106.0 tenant: 403 on a scope not held, 404 on a document out of scope, read ≠ write, read-only, a principal administers nobody, a forgotten document is not recalled. The MA e2e suite passes on 0.106.0 from this branch **and from unchanged `main`** — so the extension can be deployed before the API. |

**How it was tested without touching the live cluster.** `make install` overwrites the cluster-wide
shared library and the default extension version, and this host's cluster carries `maludb_os_memory`.
So: a relocated copy of the PostgreSQL 17 installation under `/home/maludb/maludb-mb-scratch/pg`
(PostgreSQL finds its share and lib directories relative to its own binary), its own cluster on port
5499 with a socket only, and `PG_CONFIG` pointed at the copy. Nothing was installed system-wide.
`gen/` there holds the generator that re-emits the patched workers from the catalogue (each patch
asserts it matched exactly once) — the repo itself carries only plain SQL.

**Found on the way.** (1) My first facade builder re-granted write access on `maludb_skill` when it
replaced the view, which in `maludb_public` handed the public catalogue back to every executor — the
existing `skill_discovery` test caught it; a replaced view now keeps the grants its own builder made,
and the three new skill-administration facades go to `maludb_skill_curator` there. (2) A document
created *inside* a principal-bound call was stamped with the author's home scope before the namespace
was known, so "remember this in dept:3" landed in `agent:44`; hence the adopt rule below.

**Changed from the design above.**
- *A document lives in the namespace of its first edge*: it adopts that scope when it has none, or
  when its own author has just uploaded it and nothing is embedded yet. This is what makes the
  platform's existing `remember` calls private at document level with **no API change**, and the
  upgrade backfills documents whose chunks share one namespace. `maludb_set_scope()` is the deliberate
  move.
- Principal grants on skills are a sibling table, `malu$skill_principal_access`: a dozen existing
  policies read `malu$skill_access.grantee_role` through `pg_has_role`, and making it nullable would
  have put a NULL in each.
- `presence_list` keeps its signature; the roster with cursor and TTL is a new `presence_roster`.
- `maludb_skill_register` keeps its signature: a bound session's skill becomes a proposal by trigger,
  and it no longer retires its parent until someone approves it.
- The write check is a trigger, not a policy `WITH CHECK`: two of the views are owned by the
  extension and the ingest workers are SECURITY DEFINER, and row security reaches neither.

**Owed / worth knowing.**
- PR #15 (`fix/delete-document-chunks`, API 0.2.1) is the stop-gap for engines below 0.106.0 and
  should merge first; this branch overlaps it only in the version string.
- Run transcripts and activity episodes on this server have no scope (= `default`). When the platform
  switches on the principal headers it must scope transcripts (`scope` on chat start is there for it)
  and decide which scope activity episodes belong to — until then a bound principal sees none of them,
  which is the safe direction.
- ~~Left on this server by earlier tests: three probe facts in `smoke:embed-probe` and one chunk "y" in
  `org`~~ — removed 2026-09-19 through `DELETE /v1/memory/chunks/{id}` once 0.106.0 was live.

## Not in this release

- **Draining the embedding queue on this server** (3,042 cards → OpenAI `text-embedding-3-small`,
  cents, but it is spend and an outward call): the owner's go, then the API's
  `/v1/memory/embeddings/run` on a timer. Until then `activity_recall` for ordinary users stays shut.
- **M4c** compartment-free search; **M2** delegated tokens (API); pg_password at rest.
- **Deploying 0.106.0 to `maludb_os_memory`** — `ALTER EXTENSION UPDATE` has no downgrade path; it
  waits for the owner, after the PR is reviewed. Backup first (`pg_dump -Fc maludb_os_memory`).
- The platform side: syncing principals + grants from `members` / `department_members`, passing
  the principal on every MaluDB call, and a forget action. Separate spec, checkpoint gate.

## Open Questions

| # | Question | Default taken |
|---|---|---|
| 1 | Subject / statement cards are tenant-shared vocabulary, so `semantic_search` can show a restricted principal that a *name* exists in another scope | Accepted for 0.106.0; per-scope vocabulary is a redesign of SVPOR identity, not a filter |
| 2 | Sensitivity ceiling default for a new principal | `internal` |
