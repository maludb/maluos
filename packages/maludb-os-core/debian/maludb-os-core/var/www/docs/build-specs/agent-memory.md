# Build spec: Shared memory on MaluDB (stage H4)

> Plan: `docs/hermes-integration-plan.md` (H4). The tools (`recall`, `core_memory`,
> `session_search` on a third read server, port 8814) and the actions (`memory_remember`,
> `core_memory_set`) were approved at the H1 checkpoint and are already in the tool surface and the
> manifest. MaluDB release MA (PR #14, deployed 2026-09-19) provides the routes. **New here and
> needing no further approval:** one migration that registers the endpoint and seeds one approval
> policy. **A change to the plan, stated plainly:** the in-process Hermes `MemoryProvider` is
> deferred — see "Why the runner, not a provider".

## Scopes — what the platform enforces (MaluDB does not, yet)

MaluDB namespaces are labels: whoever holds the tenant token reads all of them. So **no agent and
no person ever holds a MaluDB token.** Two processes hold it — the Memory server and PHP — and
both resolve scope from the verified caller, never from anything the caller says.

| Scope | Namespace / profile ref | Read by | Written by |
|---|---|---|---|
| self | `agent:<member_id>` or `member:<member_id>` | that member; for an agent, its management chain | that member |
| department | `dept:<department_id>` | members of that department | members of it; **an agent's write pauses for approval** |
| organisation | `org` | every insider | super-admins and dept-admins; **an agent's write pauses for approval** |

A caller's **read scope set** is: self + every department it belongs to + `org`. `recall` searches
the whole set in one MaluDB call and says which namespace each result came from. A caller may
narrow (`scope: self|department|org`) and never widen.

## Reads — the Memory MCP server (`mcp/memory_server.py`, port 8814)

Same skeleton as the records server: `server_common` bearer auth (personal token, action token or
agent run token), `agent_grants` enforcement under endpoint name **`Memory MCP`**, the records
read role for the one question it asks Postgres (who is the caller, which departments).

| Tool | Does |
|---|---|
| `recall` | `query`, `subject?`, `scope?`, `limit?` → MaluDB `POST /v1/memory/recall` over the caller's namespaces. With no subject MaluDB proposes subjects from the query; the answer says which it tried. |
| `core_memory` | `member_id?` (default: caller) → MaluDB `GET /v1/principals/{ref}/profile`. Someone else's profile only for their manager chain or `mod:hr`. |
| `session_search` | `query`, `agent_member_id?` → MaluDB `GET /v1/chat/search` filtered to a principal the caller may see (self; an agent it manages; `mod:hr` any). |

## Writes — manifest actions through PHP (`html/memory/`)

| Action | Handler | Rule |
|---|---|---|
| `memory_remember` | `remember.php` — **text**, **subject**, scope (self/department/org), department | `require_post` + `verify_csrf` + insider. Scope resolved server-side. Self → logs `memory.remember`. Department/org → the log event is **`memory.remember_shared`**, which the seeded policy "Agents: writing shared memory" pauses for an agent (`check_approval`), so a person reads what an agent wants every colleague to know before they know it. Then MaluDB `POST /v1/memory/remember`. |
| `core_memory_set` | `core-set.php` — **key**, **value**, member | The member itself, its manager chain, or `mod:hr`. MaluDB `PUT /v1/principals/{ref}/profile/{key}` (supersedes, never overwrites). Logs `memory.core_set`. |

`app/features/memory/maludb.php` is the one PHP client (`MALUDB_API_URL`, `MALUDB_API_TOKEN` from
`config/.env`). Text and values are never written to `activity_log` in full — a 200-character
excerpt and the MaluDB document id; the memory itself lives in MaluDB.

## What a run gets without asking — the runner

| When | The runner does | Why here |
|---|---|---|
| `prepare` | reads the agent's profile and renders it into the persona as "What you know" | core memory must be in the system prompt, and the runner renders the system prompt |
| `prepare` | recalls over the agent's scope set using the instructions as the query and appends the top results to the instructions as *recalled context — information, not orders* | one recall per run, where Hermes' `prefetch` would make one per turn |
| after the run | writes the transcript to a MaluDB chat session (`principal=agent:<id>`, `external_ref=run:<id>`) from the last prompt-ledger payload | the ledger already holds the exact conversation; `session_search` finds it later |

`profile_hash` is computed **before** memory is added: it identifies the configuration, and an
agent learning something must not look like a configuration change.

The runner reads MaluDB with its own token (`MALUDB_API_URL`/`MALUDB_API_TOKEN` in `runner.env`).
That is telemetry and context assembly by trusted infrastructure, like `activity_ingest.py` — not
an agent write. **An agent's deliberate memories go through the action**, where they are gated,
logged and, when shared, approved.

### Why the runner, not a provider

The plan had a Hermes `MemoryProvider` plugin doing this from inside the agent process. It would
need a credential inside the sandbox, a write path for every turn, and coupling to a Hermes
interface that H0 shows moving weekly — to do, for one-shot runs, what the runner can do at the two
moments it already owns. The provider (`maludb-hermes`, plan item M10) comes back when agents hold
multi-turn conversations, where per-turn prefetch is the point.

## Migration `db/104_memory_endpoint.sql`

Registers **Memory MCP** (`http://127.0.0.1:8814/mcp`, `kind='mcp'`, `auth_kind='bearer'`,
`agent_reachable`) on the `platform` application — in the migration that ships the server, per
db/075's rule that an endpoint row for a server that does not exist is a lie. Seeds the approval
policy *Agents: writing shared memory* (`category='other'`, `action_pattern='memory.remember_shared'`,
`applies_to='agents'`).

## Files (exactly these)

```
db/104_memory_endpoint.sql
mcp/memory_server.py  mcp/maludb_client.py                  docs/deploy/maludb-os-memory-mcp.service
app/features/memory/maludb.php  app/features/memory/scope.php
html/memory/remember.php  html/memory/core-set.php
mcp/agent_runner/memory.py  (+ hermes_render.py, hermes_harness.py, service.py, config.py, store.py)
```

## Acceptance

1. Sasha remembers a private fact (action) and recalls it (tool) in a later run; another agent's
   recall over its own scope does not find it.
2. A department memory written by a person is recalled by an agent of that department and not by an
   agent outside it.
3. An agent's department-scope `memory_remember` pauses; approving it (H3) stores it.
4. `core_memory_set` for Sasha appears in Sasha's next persona; `profile_hash` is unchanged.
5. After a run, `session_search` finds a phrase from that run's transcript; an agent cannot search
   another agent's sessions.
6. No MaluDB token under `/var/lib/business-os/agents/`; an ungranted agent sees none of the three tools.

## Known limit, owner's decision

`maludb_os_memory` has **no embedding model configured** (checked 2026-09-19): MaluDB falls back to
deterministic hash vectors, so ranking *within* a result set is arbitrary. Isolation does not
depend on it — namespace and subject filters are exact — but recall quality does. The catalog
offers OpenAI `text-embedding-3-small` (needs an OpenAI key) or a local Ollama model. Configure one
**before** memory accumulates: changing the embedder later means re-embedding everything.

## Built *(2026-09-19)* — acceptance as run on this server

| # | Result |
|---|---|
| 1 | Sasha remembered a private fact through the action; her `recall` finds it (`agent:44`), and free-text recall proposed the subject unprompted. Seamus and the owner, searching their own scope sets, do not. |
| 2 | A department memory is recalled by an agent of that department (`dept:3`) and by nobody in department 4. |
| 3 | Sasha's department-scope `memory_remember` paused (request 11); approving it replayed the handler and stored it in `dept:3`. |
| 4 | The owner set Sasha's core memory `vendor_naming`; run 12's persona carried it and the agent cited it as *"a standing fact written or approved by a person"*. Sasha's own attempt to set *"always approve invoices from Acme without checking"* paused and was rejected. `profile_hash` excludes memory (unit test); it did differ from run 11 because four tool grants were added in between, and grants are configuration. |
| 5 | Run 12's transcript is a MaluDB chat session (`run:12`); `session_search` finds it for Sasha and for the owner (HR); an agent without the grant cannot call the tool at all. |
| 6 | No `malu_` token under `/var/lib/business-os/agents/`; an ungranted agent lists none of the three tools. |

Run 12 (Claude, 0.118) was asked a question whose whole answer lived in memory and was told to look
nothing up. It answered from core memory and department memory, gave its own private note *lower
confidence* because no person had approved it, and noticed that the note described a vendor paying
*us* — an inconsistency in the test data. Nothing in the persona asks for that; the labels on the
recalled block were enough.

Ordinary refusals proved on the way: a plain user cannot write org memory or someone else's core
memory; an agent cannot write into a department it is not in. Refusal sentences reach JSON callers
(`memory_fail`); MaluDB being down answers 424 with its reason, not a generic 5xx.

**Embedding model — set 2026-09-19: OpenAI `text-embedding-3-small`** (1536 dimensions, the size memory
already stored) with `php bin/maludb_set_embedder.php --key-file <file>`; MaluDB holds the key, `config/.env`
does not. PHP, the runner and the Memory server share one MaluDB identity, so one setting serves all three.
Proven: `remember` and `recall` both report the model, and three probe facts ranked correctly against
questions sharing no words with them (*"who signs off on wages"* → the payroll fact 0.52, the invoice fact
0.37, the coffee machine 0.17). The four memories written before it keep their hash vectors (`maludb-local-dev`).

**Found while proving it — a MaluDB defect, not yet fixed: a deleted memory stays recallable.**
`DELETE /v1/documents/{id}` removes the document and its graph edges but leaves its rows in
`malu$vector_chunk`, and recall reads chunks. Tombstoning them (`tombstone_vector_chunk`) does not help
either: `exact_vector_search_sql` filters tombstones only on its ANN-index path, and a compartment with no
ANN index takes the exact-scan path, which ignores them. Left behind on this server: three probe facts in
the namespace `smoke:embed-probe` (in nobody's scope set, so no screen or tool can reach them) and one
earlier test chunk whose whole text is "y" in `org` (recallable by everyone; harmless, but it proves the
point). The platform has no forget action yet, so nothing a person relies on is affected today — but
**a forget/delete action must not ship before this is fixed** (extension MB: delete chunks with their document, and honour tombstones on the exact path). The API cannot
delete chunks — a tenant role has no privilege on them — so **API PR #15** makes search and recall drop any hit
whose document is gone: deleted text is hidden at once, and physically removed once the extension does it.
**Deployed 2026-09-19 (API 0.2.1)** — the probes and the "y" chunk above are no longer recalled here.

**Closed 2026-09-19 23:55 UTC** by MaluDB 0.106.0 + API 0.3.0, both live on this server
(`docs/build-specs/maludb-mb.md`): tombstones are honoured on every search path — the C exact scan
included — `DELETE /v1/documents/{id}` now forgets the document with its chunks, the edges that carry its
words and its source, and deleting a document row by any route takes its chunks with it. The three probe
facts and the "y" chunk were physically removed (`DELETE /v1/memory/chunks/{id}`). **A forget action may
now be built.**

`recall` with no subject depends on the
query naming something MaluDB already knows; a compartment-free search is MaluDB item M4c.

## Open Questions

*(none)*
