# Federated memory (db/192) — the kernel half of Phase 13 slice 4

Built 2026-10-31 from the MaluOS specification `docs/phase13-slice4-memory.md` (maluos repository), on top of the
nodes (db/188), the overlay (db/189), the directory and the envelope (db/190) and shared inference (db/191). Proof:
`BOS_INTERNAL_URL=http://127.0.0.1:8089 php bin/test_estate_memory.php` (74 checks with db/193, re-runnable; the office's own
recall is stubbed where MaluDB is not running, as on this host).

## What it does

Every MaluOS host is a memory host; the slice gives each a **memory face** that answers scoped queries for the estate.
Each member's heartbeat carries its **memory facts** (the departmental and enterprise scopes its face holds, how much,
how fresh, which it shares, its ceiling, its port); the kernel keeps them beside the inference facts and publishes, per
member, the **holders** it may ask scope by scope (`endpoints.memory`, real at last: null since Phase 12) and, per
holder, the **peers** allowed to ask it with their ceilings (the signing keys stay at `/api/v1/estate/keys`). The
kernel never relays a query: the member's face asks the holders over the overlay with the slice 2 envelope as the
credential. **The office is a holder too**: `POST …/memory/query` answers from the agent-memory stage H4
(`memory_recall()` over namespaces narrowed to what the caller may read) as **claims**, never records. Who may read
what is the **policy** (`estate_memory_policy`); the defaults: every active member reads `org`, a desk the `dept:N`
scopes of its owner's departments, a server or inference node every department, at an `internal` ceiling; a desk
holder never serves another desk (the plan's decision 5). A rule may mark a scope's summaries for replication.

## Schema (db/192, additive)

| Table or column | Holds |
|---|---|
| `estate_memory` | one row per member that reported facts: `scopes jsonb` [{scope, count, updated_at, kinds}] (shareable scopes only: a personal scope in the facts is dropped, never stored), `shared jsonb` (sorted), `max_classification` (the host's own ceiling), `port` (11437), `api_version`, `signature` (the scopes held and shared, the ceiling, the port: a change bumps the version; the counts never do), `updated_at` |
| `estate_memory_policy` | the rules: `subject` org / dept:N / kind:desk|server|inference / node:ID, `scope` org / dept:N / `*`, `holder_location_id` (null = any, the office included), `allow`, `max_classification`, `replicate`, `priority`, `note` |
| `estate_memory_settings` | one row: `version` (the holders), `peers_version` (the peers), `fanout_max` 8, `rate_per_min` 30 |
| `locations.memory_seen_version`, `memory_peers_seen_version` | what the member last heard (the heartbeat flags) |

## Contract additions (app/features/estate/memory.php)

| Endpoint | Token | Answer |
|---|---|---|
| `POST /api/v1/estate/join`, `POST /api/v1/desks/enroll` | code | `endpoints.memory` (`…/estate/memory` for a node, `…/desks/memory` for a desk), `endpoints.memory_peers` |
| `POST /api/v1/estate/heartbeat`, `POST /api/v1/desks/heartbeat` | node / desk | takes `memory: {scopes, shared, max_classification, port, api_version}` (≤ 8 KB, 400 over); answers `memory_changed`, `memory_peers_changed` |
| `GET /api/v1/estate/memory`, `GET /api/v1/desks/memory` | node or desk | `{self, holders: [{node, id, kind, name, display_name, address, port, api_version, max_classification, scopes: [{scope, count, updated_at, kinds, classification_max, replicate, priority}], updated_at}], office: {query, scopes: [{scope, classification_max, label}]}, fanout_max, rate_per_min, refresh_s 3600, version}`; never the caller; only online, sharing members with an overlay address; each scope filtered by the policy. `?all=1` from an operator's desk: every shared scope with `allowed` |
| `GET /api/v1/estate/memory/peers` | node or desk (a holder) | `{self, shared, peers: [{node, id, kind, name, display_name, address, public_key (the peer's signing key from db/190, null when it registered none), scopes: [{scope, classification_max, replicate, priority}]}], keys, refresh_s 300, version}` |
| `POST /api/v1/estate/memory/query` | node, **with an envelope** | `{envelope, scopes, query, classification, limit ≤ 50}` → `{holder: "coordinator", claims: [{text, scope, kind, sensitivity, confidence, observed_at, recorded_at, source: {node, object, id, ref}, writer, holder, rank}], scopes_read, scopes_asked, truncated, count}`; errors 400 `invalid`, 401 `bad_envelope` / `bad_signature` / `expired`, 409 `replay`, 403 `forbidden` (a scope outside the policy or the envelope's authority) / `classification`, 429 `rate`, 503 `memory_unavailable` |
| `POST /api/v1/desks/memory/query` | desk | the same without the envelope: the desk's owner is the principal; `self` is a scope too (the owner's own namespace) |

The versions: a member's facts bump `version` only when the published view changes (a scope held or shared, the
ceiling, the port); a rule, a join or a retirement bump both. A read of the holders or the peers marks that version
heard. **The policy's precedence**: the most specific subject wins (node:ID 3 > dept:N 2 (a desk's owner's
departments) > kind:K 1 > org 0); at the same depth a rule naming one holder beats one for any, then a rule naming one
scope beats one for `*`, then a deny beats an allow. **The office's query** verifies a node's envelope with
`envelope_verify()` bound to the token's node (the nonce consumed: a second use is `replay`), requires the envelope's
`authority.scopes` to cover every scope asked and its classification to cover the request's, applies the policy with
the office as the holder (`['id' => 0, 'kind' => 'coordinator']`, so holder-specific rules never match it), rate-limits
by the activity rows of the last minute, and writes one `memory.query` activity row per answered query: the scopes
asked and read, the count, the classification, the envelope id, the task id and the originator, never the text.

## Departures from the MaluOS text, and why

1. **No `GET …/memory/summaries` at the office.** The H4 memory has no summary kind to publish; replication (the
   plan's decision 9) pulls summaries from node holders through their faces. The office's summaries wait for a
   memory kind on its own writes.
2. **The claim's `confidence` is what the writer gave** (`payload_jsonb.confidence` on a host's memory; the recall
   result's `confidence` at the office) or null; the engine's similarity is never shown as confidence (the H4 stage's
   own rule: with no embedding model it is arbitrary).
3. **`self` as a desk's query scope**: the owner's own namespace at the office, which the H4 Memory MCP already
   narrows to; a node's query has no self.
4. **Settings → Desks, not a new page**: the Memory section joins the Inference section (`present_memory_for_settings()`;
   `html/settings/desks/memory.php` for the rules and the limits).

## Where it lives

`db/192_estate_memory.sql`; `app/features/estate/memory.php` (loaded by `nodes.php` and `desks.php`);
`html/api/v1/estate/memory.php` (`?sub=peers|query`), `html/api/v1/desks/memory.php` (`?sub=query`); the heartbeat,
join and enrol endpoints; `node_retire()` / `desk_retire()` → `memory_member_retire()`; `html/settings/desks/memory.php`;
`web/components/settings/MySettings.tsx` (`Memory`) and `web/lib/schemas/settings.ts`; `docs/deploy/apache-react-cutover.conf`
(the allow-list).

## db/193: the Memory MCP for desks, and a host with two memberships (MaluOS slice 4b, 2026-11-01)

Built from `docs/phase13-slice4b-memory.md` (maluos), decisions 6, 7 and 9. Proofs: `bin/test_estate_memory.php` (74),
`bin/test_desk_enrolment.php`, `python3 bin/test_memory_mcp_desk.py` (9: the relay against a fake office, no Postgres).

| Change | Where |
|---|---|
| `mcp_resolve_token()` answers `token_scope` and `location_id` beside the member and the role (a desk token names its desk; a node token still never resolves) | `db/193_memory_mcp_desks.sql` |
| The MCP middleware keeps them in the request context with the raw bearer (`db.request_token_scope`, `request_location_id`, `request_token`) | `mcp/db.py`, `mcp/server_common.py` |
| **The Memory MCP's `recall` from a desk token relays** to `GET /api/v1/desks/memory` (the office's scopes for the desk) and `POST /api/v1/desks/memory/query` with the same bearer, the tool's scope (`self`, `department`, `org`, none) mapped onto those scopes: the estate policy, the ceiling, the rate and the `memory.query` row are PHP's, the answer the one the desk's CLI gets. `core_memory` and `session_search` act as the owner, as the records and activity MCPs do. `APP_URL` (config/.env) or `BOS_INTERNAL_URL` names the office | `mcp/memory_server.py` |
| `/mcp/memory` proxied to 127.0.0.1:8814 like records and activity; the rewrite pass-through | `docs/deploy/apache-mcp-proxy.conf`, `docs/deploy/apache-react-cutover.conf` |
| `endpoints.memory_mcp` at enrol, heartbeat and me (`memory` stays the holders view) | `app/features/estate/desks.php` |
| **A desk whose machine id is an active node's is not a memory holder**: its face is the node's, published as the node (the office allocated the desk an overlay address its host never carries). Settings → Desks says why ("the node X of the same host") | `memory_holder_rows()`, `memory_holder_is_other_membership()`, `memory_holder_published()` in `app/features/estate/memory.php` |
