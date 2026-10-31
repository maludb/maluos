# Phase 13 slice 4: federated memory (D4)

Specified 2026-10-31 from docs/phase13-estate.md (slice 4, decisions 2,
4, 6 and 9), on top of slice 1 (nodes and reports), slice 1b (the
overlay: every member at `NAME.internal`), slice 2 (the directory, the
signing keys, the envelope with its `authority.scopes`) and slice 3
(facts in the heartbeat, a per-member view published by the kernel and
cached by the host, a policy with subjects and ceilings). Nothing here is
built. The three repositories were surveyed first (the host, the kernel,
maludb-core 0.106.0); what the survey found that the plan did not expect
is in "What exists to build on" and shapes decisions 1, 6 and 12.

The edition: the owner's line of 2026-10-25 covers inference (Community
first, the estate-wide scheduler paid). This specification recommends
the same for memory: everything here is Community; the only candidate
for a paid service is federation between estates (slice 6). Decision 12.

## What the slice delivers

An agent gets the fact it is entitled to, with its source, confidence,
time and scope, not the record it came from, from any machine of the
estate that holds it. Every MaluOS host is already a memory host (its
own MaluDB tenant, the principals and scopes of its agents). This slice
gives each host a **memory face**: one service that answers memory
queries for local principals over a socket and for the estate over the
overlay, binding every query to a principal and a scope set before the
engine runs it. The host's heartbeat carries its **memory facts** (the
departmental and enterprise scopes it holds, how much, how fresh, which
of them it shares); the kernel keeps them beside the inference facts and
publishes, per member, the **holders** it may ask for each scope and,
per holder, the **peers** allowed to ask it; the office's own memory (the
kernel's agent-memory stage) is one holder more, reachable over HTTPS,
and the enrolment contract's `memory` endpoint, null since Phase 12,
becomes real. A query that leaves a host carries the **envelope** of
slice 2, a task's or one the host signs for its own principal, so the
holder authorises the originator and the delegated scopes against its
own policy, independently of the sender. The answer is **claims**: text
with scope, sensitivity, confidence, time, source and holder; the payload
behind a claim never leaves the host that owns it. Knowledge summaries
can be copied to other hosts under a rule, provenance kept, so a desk
has the organisation's summaries at hand when the holder is away.

```
maluctl memory status                                      # the face: socket, overlay port, the guest principal, the shared scopes
sudo maluctl memory share dept:3 org [--max restricted]    # what this host serves to the estate (nothing by default)
maluctl memory remember "…" --scope dept:3 [--confidence 0.9 --source hr:training/118 --sensitivity internal --detail JSON]
maluctl memory recall "forklift training" [--scope dept:3] [--estate] [--classification internal] [--json]
maluctl memory sync                                        # copy the summaries the rules replicate to this host
sudo maluctl memory usage [--since 1h]                     # the queries this host answered and asked, never their text
maluctl estate memory [--refresh]                          # a node: the facts it reports; the holders and the peers the kernel publishes
maluctl office memory [--refresh] [--all]                  # a desk: the same; --all (operator) every holder with its scopes
maluctl office memory recall "…" --scope org               # the office's own memory, as the desk's owner
```

## What exists to build on

| Piece | Reused as |
|---|---|
| maludb-core 0.106.0 principals and scopes (`maludb_principal`, `maludb_principal_scope`, `home_scope`, `max_sensitivity`; the session settings `maludb_core.principal_ref`, `principal_scopes`, `principal_readonly`; docs/principal-scoping.md in maludb-core-26) | the engine's own enforcement: a RESTRICTIVE row policy on memories, episodes, documents, source packages and chat sessions (scope ∈ the principal's read set, sensitivity ≤ the principal's ceiling), and `_principal_assert_scope` in the search and ingest workers. **It does not reach claims, facts, SVPOR statements or edges** (tenant-wide, docs/principal-scoping.md "What this is not"), and `malu$claim` has no confidence column; confidence lives on statements, edges and pending claims. The face serves what the engine enforces (decision 6). |
| The MC2DB listener (maludb-mc2dbd 0.106.0, 127.0.0.1:5329) | unchanged. It checks one shared bearer token, never sets `maludb_core.principal_ref`, and passes `X-MaluDB-User` unverified; per-caller identity is its deferred item R1.1-7. The plan's "remote queries through the MC2DB listener" cannot be built on it as it is; the face is the service that binds the principal per request, which is the 0.106.0 doctrine ("the trust boundary is a service that sets them per request"). The listener stays the tool catalogue (`maluos.model_status`). |
| Agents as principals (maluos-agent; docs/agents.md) | `agent:NAME` with home scope `agent:NAME` and `--scope SCOPE:read|write` grants, made with `maludb_principal_upsert` and `maludb_principal_grant_scope` at create. Found: agent.py:378 splits `dept:3:read` at the first colon (scope `dept`, level `3:read`); only `org:read` was ever tested. Fixed in this slice. The unit gets `MALUDB_MC2DBD_URL` and no token: agents have no working memory path on a MaluOS host today; the face is that path. |
| The vault's identities (vault.yaml, gateway.yaml `identities: {agent-NAME: agent:NAME}`) | the face's map from a socket peer's uid to a principal, as the vault and the gateway do it. `maluos_record_episode` (the daemons' narrow write) stays for the gateway's episodes. |
| Firstboot's memory tenant (`maluos`, `enable_memory_schema`, the listener's role and token, `human:admin` with home scope `org`) | the face's PostgreSQL role (a tenant login, since only a tenant login may set the principal settings) and the **guest principal** `estate:guest` (kind `service`, ceiling `internal`) made at provision. |
| Slice 2's envelope (packages/maluos-estate/lib/maluos_estate/envelope.py: `make`, `sign`, `verify`, `Nonces`, `Keys` from `GET /api/v1/estate/keys` cached in `/run/maluos/estate/keys.json`; `authority.scopes` "memory scopes with a level", recorded for slice 4; the task result's `provenance.scopes_read: []`) | the credential of every remote query (decision 4) and the field this slice fills. |
| Slice 3's pattern (facts in the heartbeat ≤ 8 KB; `estate_inference_settings.version` / `peers_version`; `*_seen_version` per member; `*_changed` flags on the heartbeat answer; per-member answers that stamp the version heard; the policy with subjects org / dept:N / kind:K / node:ID, precedence by depth, backend-specific over any, deny over allow; a desk's contribution never for other desks; the host caches in `/run/maluos/estate/*.json` and `/run/maluos/office/*.json`, merged on a host that is both) | copied for memory: `estate_memory`, `estate_memory_policy`, `memory_version` / `memory_peers_version`, `memory_changed` / `memory_peers_changed`, the holders and peers answers, `memory.json` and `memory-peers.json`. |
| The kernel's agent-memory stage H4 (maludb-os-core docs/build-specs/agent-memory.md: namespaces `member:<id>` / `agent:<id>`, `dept:<id>`, `org` on the office's memory database `maludb_os_memory` through maludb-api; `memory_recall()`, `memory_read_scopes()`, `memory_openable_agents()` in app/features/memory/reads.php; the Memory MCP on 8814 narrowing a caller to its own namespaces; `memory_remember` and the `memory.remember_shared` approval) | the office as a holder: the same recall, answered to nodes and desks in the claim shape of decision 6. Its namespaces already name the same departments the estate's `dept:N` do. |
| The enrolment contract (docs/desk-enrolment.md: `endpoints.memory` null "until the office decides to publish them to desks, the kernel's D2 security decision"; `MALUOS_OFFICE_MEMORY_MCP` in office.env; the mock's `/mcp/memory` answering `office.ping`; the session's `endpoints.memory` boolean) | `endpoints.memory` becomes `…/api/v1/desks/memory` (decision 7); the mock answers the memory contract. |
| The Agents app (maluos-agents: the Memory page listing the agent's vault compartment, "claims with provenance come with Phase 13 slice 4"; `agent_memory` in bin/maluos-agents) | the page made real: claims from the face for a local agent, from the office for an office agent. |
| The ledger (maluos_ledger in the vault schema; `sudo maluctl gateway usage`) and the kernel's `activity_log` (`log_activity`, source `node` / `desk`) | one row per answered and per asked query, the counts and the scopes, never the text (decision 10). |
| maludb-core's local memory nodes (`malu$local_memory_node`, `node_submit` / `node_accept`: "nodes submit proposals, the server never trusts node payloads as authoritative"; the wire protocol not built) | not used in this slice; the same doctrine. Replication here is a pull of summaries (decision 9). |

## Decisions

1. **One memory face per host, in a new package `maluos-memory`.** A
   service `maluos-memory.service` (user `maluos-memory`, hardened like
   the vault) listens on `/run/maluos/memory.sock` for local principals
   and, when the host exposes it, on the overlay address at port 11437
   (the gateway's node API is 11435, its facts 11436) for the estate. It
   is the only process on the host that opens principal-bound sessions
   on the memory tenant: every query runs inside `BEGIN; SET LOCAL
   maludb_core.principal_ref = …; SET LOCAL maludb_core.principal_scopes
   = [the narrowed set]; SET LOCAL maludb_core.principal_readonly = on`
   and the engine's row policies and scope assertions do the rest. Not
   the gateway (it is the model gateway), not the listener (decision 1's
   survey line), not inside maluos-estate (a standalone desktop needs
   the local half without an estate). `maluctl memory` is its CLI; the
   agent's unit gets `MALUOS_MEMORY_SOCKET`.
2. **The three classes are the scopes, and the scopes are estate-wide
   names.** Personal memory is the principal's home scope (`agent:NAME`,
   `user:LOGIN`, `human:admin`); departmental is `dept:N` where N is the
   kernel's department id (the kernel's own memory already uses
   `dept:<id>`); enterprise is `org`. The same string on two hosts is the
   same scope. **Personal memory is never served over the estate in this
   slice**: it stays on the host where the principal lives, readable by
   the principal and, for an agent, by its owner (a read grant on
   `agent:NAME` to the owner's principal at `agent create`). A person's
   memory following them to another machine is deferred.
3. **A memory lives where it was written; its host answers for it; the
   kernel is the index, never the store.** A query for a scope goes to
   the holders the kernel publishes for that scope (the hosts whose facts
   say they hold and share it, filtered by the policy), in parallel,
   bounded (at most 8 holders, 2 s each, `MALUOS_MEMORY_FANOUT_S`), the
   answers merged by rank with each claim naming its holder; a holder
   that does not answer is reported in `holders_failed`, never waited
   for. No multi-master, no copy of the payload anywhere (decision 6 of
   the plan).
4. **The envelope is the credential.** Every query that leaves a host
   carries a slice 2 envelope: the task's when the caller works under
   one (the task runner passes it), otherwise a **self-envelope** the
   caller's host signs with its node key (`originator` = the principal,
   `sender` = the same, `target` = `{"node": "server:57"}` or
   `{"node": "coordinator"}`, `purpose` = "memory", `authority.scopes` =
   the scopes asked with level `read`, `classification` = the request's,
   `life_s` 120). The holder verifies the signature against
   `/run/maluos/estate/keys.json` (refreshed on a miss), the expiry and
   the nonce (slice 2's `Nonces`), and rejects an envelope whose
   `authority.scopes` do not cover the scopes asked. No second key: the
   inference key of slice 3 exists because G2's node API is a bearer-token
   API; memory starts after the envelope and needs nothing else. The
   plan's decision 2 verbatim: who originated it, what is asked, what
   authority was delegated, the classification, an expiry.
5. **Authorisation on the holder is an intersection, and deny wins.** A
   claim is served when every one of these allows the scope: (a) **what
   the host shares**: the operator's `maluctl memory share` list, kept as
   the guest principal's read grants, nothing by default, with the host's
   ceiling `--max` (the guest principal's `max_sensitivity`, `internal`
   by default); (b) **the estate's policy**: the kernel's rule for
   (subject, scope, holder) with its `max_classification`, from the
   holder's cached peers view; (c) **the envelope's authority**: the
   scopes delegated to the originator, with the originator's node's own
   limits already applied when it signed; (d) **the request**: the scopes
   and classification asked. The policy's default: every active member
   may read `org`; a desk may read the `dept:N` scopes of its owner's
   departments; a server or inference node may read every `dept:N`
   (servers are the organisation's machines; their agents' own scope
   grants are the limit, carried in the envelope); the ceiling is
   `internal`; `restricted` needs a rule and the host's `--max
   restricted`; `prohibited` never leaves a host. A desk holder serves
   servers and the coordinator only, never another desk (slice 3's
   decision 4, for the same reason: a person's machine). Precedence as
   slice 3: node:ID > dept:N > kind:K > org; a rule naming one holder
   beats one for any; deny beats allow at the same depth.
6. **The answer is claims, never records, and only what the engine
   enforces.** A claim is `{text, scope, kind, sensitivity, confidence,
   observed_at, recorded_at, source: {node, object: "memory"|"episode"|
   "document", id, ref}, writer, holder, rank}`: `text` is the memory's
   `summary` or the retrieval snippet, `source.ref` the writer's
   `--source` string or the document's title, `confidence` what the writer
   gave (`payload_jsonb.confidence`, 0 to 1) or null, `writer` the
   principal that wrote it. `payload_jsonb`, the document body, the chat
   messages and the `--detail` JSON never leave the holder; a local
   caller with `write` on the scope may ask `--detail` for its own host's
   rows. The face queries the tenant's scoped search facade (the memory
   search worker that asserts the principal's scope and applies the
   ceiling; the exact facade name confirmed at build time against
   maludb-core 0.106.0) over memories, episodes and documents. **SVPOR
   statements, claims and facts are not served remotely** in this slice:
   in 0.106.0 they are tenant-wide and the engine cannot narrow them to a
   scope; serving them would violate the plan's "never the record it came
   from". Two maludb-core follow-ups are filed for the owner's other
   repository (Deferred): scope and principal on statements and claims;
   principal binding in the listener. The face's shape does not change
   when they land; the kinds served grow.
7. **The office is a holder, and `endpoints.memory` becomes real.** The
   kernel answers `POST /api/v1/estate/memory/query` (a node token plus
   an envelope) and `POST /api/v1/desks/memory/query` (a desk token; the
   desk's owner is the principal, no envelope needed since the token is
   the desk's) from its H4 memory with `memory_recall()` over namespaces
   narrowed to what the caller may read: the owner's own, the owner's
   departments, `org`; an office agent's namespace when
   `memory_openable_agents()` allows. That is the D2 security decision of
   Phase 12, taken: the answer is claims, the rate is 30 queries a minute
   per desk, the activity row says `surface desk`. `endpoints.memory` =
   `…/api/v1/desks/memory` (the holders view, with `query` beneath it);
   `MALUOS_OFFICE_MEMORY_MCP` keeps its name for the agents' environment
   and now holds that URL. The Memory MCP on 8814 is not published to
   desks in this slice (Deferred).
8. **Writes stay local and stay what they are.** `maluctl memory
   remember` writes to the caller's own host as the caller's principal:
   the home scope always, `dept:N` or `org` with a `write` grant on the
   scope (`--scope dept:3:write` at `agent create`; an operator's
   principal has `org:write`). An agent without the grant is refused
   `scope_write`; this slice does not route it to an approval (the
   kernel's `memory.remember_shared` pauses for one; on the host the
   operator grants the scope or does not). No remote writes: a memory
   about the organisation written on a server stays the server's. Kinds:
   `note` (default), `summary` (decision 9), `observation`; `--sensitivity`
   as the gateway's (`public`, `internal`, `restricted`, `prohibited`),
   default `internal`.
9. **Replication is a pull of summaries under a rule, provenance kept.** A
   rule with `replicate` on lets the subject copy the holder's
   `summary`-kind memories of the scope: `maluctl memory sync` (the
   estate service runs it hourly and on `memory_changed`) asks each such
   holder for `kind=summary` since its last version and writes them into
   the local tenant as memories of the same scope and sensitivity with
   `payload_jsonb.origin = {node, id, version, copied_at}`, read-only to
   everyone (the face refuses to edit a memory with an origin), replaced
   when the holder's version moves, tombstoned when the holder retracts.
   A local recall then answers them with `holder = this host` and
   `origin = server:57`. Nothing else is replicated. This is the part to
   drop first if the slice must shrink; the proof's scenario does not need
   it.
10. **Every query is in two ledgers and in no transcript.** The holder
    writes `memory.query` to its ledger: the originator, the envelope id,
    the task id, the scopes asked, the scopes read, the classification,
    the count, the holders' failures; the caller writes `memory.recall`
    with the holders asked; the kernel writes `memory.query` to
    `activity_log` for the office's answers. Never the query text, never
    a claim. A task's result gets `provenance.scopes_read` from the task
    runner (the union of the scopes its queries read) and
    `provenance.holders`. `sudo maluctl memory usage` reads the host's
    rows; the Agents app's Memory page shows an agent's claims with their
    holders and the last queries.
11. **The operator's view.** Settings → Desks gains a Memory section (as
    the Inference section): every holder with its scopes, counts and
    freshness; the rules (add, remove); the office's own scopes. The
    System Monitor's MaluOS Network tab counts memory holders in the
    Estate group's line ("3 nodes, 2 memory holders"); nothing more in the
    fork this slice.
12. **Edition: Community**, recommended. Memory sharing inside one estate
    is what makes the estate an estate; the paid line stays where the
    owner put it (the scheduler, SSO, many coordinators), and federation
    between estates (slice 6) is the next candidate.

## Contract (surface 1), the kernel half for approval

- **db/192**: `estate_memory` (one row per member that reported facts:
  `scopes jsonb` [{scope, count, updated_at, kinds}], `shared text[]`,
  `max_classification`, `port int`, `api_version`, `signature`,
  `updated_at`); `estate_memory_policy` (`subject` = org | dept:N |
  kind:desk|server|inference | node:ID, `scope` = org | dept:N | `*`,
  `holder_location_id` or null = any, `allow boolean`,
  `max_classification`, `replicate boolean`, `priority int`, `note`);
  `estate_memory_settings` (one row: `version`, `peers_version`,
  `fanout_max 8`, `rate_per_min 30`); `locations.memory_seen_version`,
  `memory_peers_seen_version`. Additive; RLS and grants as db/191.
- `POST /api/v1/estate/heartbeat`, `POST /api/v1/desks/heartbeat` take
  `memory: {scopes, shared, max_classification, port, api_version}` (≤ 8
  KB, 400 over; personal scopes never reported); the answer carries
  `memory_changed` and `memory_peers_changed`. The version bumps only
  when the published view changes (a scope appears or goes, the shared
  list, the ceiling, the port), never for counts alone; a rule, a join,
  a retirement bump both.
- `GET /api/v1/estate/memory`, `GET /api/v1/desks/memory` (a node or
  desk token): `{self, holders: [{node, id, kind, name, display_name,
  address, port, api_version, scopes: [{scope, count, updated_at,
  classification_max, replicate}]}], office: {url, scopes: [org, dept:N…]},
  fanout_max, refresh_s 3600, version}`; never the caller itself; only
  shared scopes of online members with an overlay address; filtered by
  the policy and decision 5's defaults; `?all=1` from an operator's desk
  lists every holder with `allowed` per scope.
- `GET /api/v1/estate/memory/peers` (a node or desk token; a holder):
  `{self, peers: [{node, id, kind, name, address, scopes: [{scope,
  classification_max, replicate}]}], refresh_s 300, version}`. The
  signing keys stay where slice 2 put them (`GET /api/v1/estate/keys`).
- `POST /api/v1/estate/memory/query` (a node token; body `{envelope,
  scopes, query, classification, limit ≤ 50, since?}`) and `POST
  /api/v1/desks/memory/query` (a desk token; body without the envelope):
  `{claims: [decision 6's shape with holder "coordinator"], scopes_read,
  truncated}`; errors `forbidden` (a scope outside the caller's set,
  with the scope named), `classification`, `bad_envelope`, `rate`.
  `GET …/memory/summaries?scope=&since=` for decision 9's pull from the
  office's own summaries.
- Settings → Desks → Memory (`present_memory_for_settings()`,
  `html/settings/desks/memory.php` for the rules; the React MySettings
  `Memory` card). `node_retire()` / `desk_retire()` →
  `memory_member_retire()` (facts forgotten, both versions bumped).
- Proof `bin/test_estate_memory.php` (the defaults, each rule depth, a
  desk never served to a desk, the ceiling, the office's query narrowed
  to the owner's namespaces, the envelope's scopes narrower than the
  request, the versions and flags, retirement).

## The host half

- **maluos-memory 0.1.0 (new)**: `lib/maluos_memory/{server,engine,
  envelope_gate,sync,cli}.py`; `maluos-memory.service`; the PostgreSQL
  role `maluos_memory` (a tenant login of `maluos`), the guest principal
  `estate:guest`, both made by a firstboot component (`50-maluos-memory.py`,
  maluos-firstboot 0.1.13) after the listener's; the socket with peer
  credentials mapped through the vault's identities; the overlay listener
  bound by `sudo maluctl memory expose --bind overlay` (as the gateway's)
  and recorded in the facts; `maluctl memory status|share|unshare|expose|
  remember|recall|forget|sync|usage|peers`; the facts file
  `/run/maluos/memory/facts.json` for the estate and desk services; the
  ledger rows through the vault's ledger as the gateway writes them;
  tests/memory-local-test.sh (the face alone: principals, scopes, the
  ceiling, a self-envelope verified against a local key file, the claim
  shape, the detail never in a remote answer).
- **maluos-estate 0.5.0**: the heartbeat carries `memory` from the facts
  file; caches `/run/maluos/estate/memory.json` and `memory-peers.json`
  with `secret_ref` as slice 3; `maluctl estate memory [--refresh]`;
  `sync` hourly and on `memory_changed`; the mock office's memory contract
  (`/api/v1/{estate,desks}/memory`, `/peers`, `/query` answering canned
  claims from "coordinator", `/mock/memory` to set rules and the office's
  claims; `/mock/state` lists the queries it answered).
- **maluos-desk 0.8.0**: the desk heartbeat carries `memory`; caches
  `/run/maluos/office/memory.json`, `memory-peers.json`; `maluctl office
  memory [--refresh] [--all]` and `maluctl office memory recall`;
  office.env's `MALUOS_OFFICE_MEMORY_MCP` set from `endpoints.memory`.
- **maluos-agent 0.6.0**: `--scope dept:3:read` parsed with `rpartition`
  (the found bug); the unit's `MALUOS_MEMORY_SOCKET`; `agent create
  --owner` grants the owner `agent:NAME:read`; the task runner passes the
  task's envelope to the face (`MALUOS_TASK_ENVELOPE` already in the run's
  environment) and fills `provenance.scopes_read` and `holders` from the
  face's per-envelope ledger rows; the demo agent answers a "what do we
  know about …" task with a recall over the estate.
- **maluos-agents 0.4.0**: the Memory page real: a local agent's claims
  (`maluctl memory recall --as agent:NAME`, allowed to the owner), the
  scopes it may read and write, its last queries; an office agent's
  through `endpoints.memory`; the self-test covers it.
- **maluos-session 0.12.0**: `office.memory` in the state (holders count,
  the office's scopes); the Network tab's Estate line counts holders
  (maluos-system-monitor 49.1+maluos.6, one string).
- Gateway: unchanged. Vault: unchanged (the ledger table takes the new
  events as it took the gateway's).

## Test (tests/qcow2-boot-test.sh, both profiles, after slice 3's steps)

The one VM is desk:41 and server:57 at once, as in slice 3; the mock
office publishes the policy. The HR scenario of the plan on one host:

1. **The face.** `maluctl memory status`: the socket, the guest principal
   with no grants, nothing shared, not exposed. `sudo maluctl memory
   expose --bind overlay`; `sudo maluctl memory share dept:3 org`; the
   facts file lists both; within a heartbeat the mock's `/mock/state`
   shows the node's memory facts (scopes dept:3 and org, port 11437).
2. **Writes as principals.** `sudo maluctl agent create hr --scope
   dept:3:write --scope org:read …`; as `agent-hr`: a dept:3 note "Alex
   completed forklift training on 2026-09-01" with `--confidence 0.9
   --source hr:training/118 --detail '{"certificate": "FL-2231"}'`; a
   dept:3 note `--sensitivity restricted`; an org summary; a dept:9 write
   refused `scope_write`; `maluctl memory recall` as `agent-hr` answers
   the two dept:3 rows with the detail of its own host's row on
   `--detail`; as user `maluos` (no grant) the dept:3 recall answers
   nothing and `--scope dept:3` is refused `forbidden`.
3. **The holders.** `maluctl office memory --refresh`: holders server:57
   with dept:3 (the desk owner's department in the mock) and org, no
   dept:9; the office's own scopes; `maluctl estate memory` shows the
   peers: desk:41 for dept:3 and org at `internal`.
4. **The federated query.** As user `maluos` on the desk: `maluctl memory
   recall "forklift training" --scope dept:3 --estate --json`: one claim
   from holder server:57 with text, scope dept:3, confidence 0.9, source
   hr:training/118, writer agent:hr, no `detail`, no `payload`; the
   restricted row absent; `--classification restricted` refused
   `classification`; `--scope dept:9` refused `forbidden` by the holder
   (not by the cache); the query went over 100.100.0.1:11437 with a
   self-envelope signed `desk:41` (the holder's ledger row names it).
5. **The envelope.** A query with a tampered signature → `bad_signature`;
   the same envelope twice → `replay`; an envelope with
   `authority.scopes: ["org:read"]` asking dept:3 → `forbidden`; an
   expired one → `expired` (the test signs these with the desk's key by
   hand, as slice 2's test does).
6. **The rules.** `/mock/memory` adds deny `kind:desk` on dept:3 at
   server:57; `maluctl office memory --refresh` drops the scope from the
   holder and `sudo maluctl estate memory --refresh` drops the desk from
   the peers; the query is refused `forbidden`; the rule removed, served
   again. A rule `replicate` on org: `maluctl memory sync` copies the org
   summary into the desk's tenant with `origin server:57`; a local recall
   answers it with the origin; `maluctl memory forget` on it is refused
   `origin`.
7. **The office as a holder.** `maluctl office memory recall "safety"
   --scope org` answers the mock's canned claim with holder
   `coordinator`; the mock's `/mock/state` shows the query with the
   desk's scopes and no text.
8. **The task.** `maluctl agent send me "what training does Alex have"`:
   the demo agent's recall carries the task's envelope; `maluctl estate
   tasks <id>` shows `provenance.scopes_read: ["dept:3"]` and `holders:
   ["server:57"]`; the holder's ledger row carries the envelope id and the
   task id.
9. **The ledgers and the app.** `sudo maluctl memory usage --since 1h`:
   the answered queries with scopes and counts and none of the texts;
   the Agents app self-test's Memory page lists agent hr's two claims (as
   the owner) with holder `this host`.
10. **Retirement.** The mock retires the node: the holder leaves the
    desk's cache at the next refresh; the guest principal keeps its grants
    (the host's own choice).

Server profile: steps 1, 2, 3 (as a node: the facts, the peers) and 5
through the overlay address with a node self-envelope, and 10.

## Status

Specified 2026-10-31. The owner settled the open decisions the same
day: 12 as recommended (Community), 9 in the slice (replication of
summaries), 1 the new package `maluos-memory`, 5 as recommended (a desk
holder never serves another desk; servers read every department by
default), and the two maludb-core follow-ups of decision 6 started in
parallel in maludb-core-26 (scope and principal on statements, claims and
facts; principal binding in the MC2DB listener). The kernel half (db/192)
is next; nothing built yet.

## Deferred

- **maludb-core**: scope and principal on SVPOR statements, claims and
  facts (then the face serves them as claims with the engine's own
  confidence); principal binding in the MC2DB listener (R1.1-7); the
  local memory node wire protocol (then replication can be push and
  cover more than summaries).
- Personal memory following a person to another machine (a desk's
  owner's scope readable from a server they sign in to).
- Remote writes and the approval of an agent's shared write on the host
  (the kernel's `memory.remember_shared` flow, on the Desk as a grant
  request).
- The Memory MCP (8814) published to desks over HTTPS; the records and
  activity MCPs are already there.
- Embeddings: hosts without an embedding model fall back to the engine's
  hash vectors; `maluctl gateway ollama pull nomic-embed-text` and the
  engine's embedding configuration are a firstboot option, not this
  slice.
- Residency rules (a scope that must not leave a host or a site) beyond
  the ceiling and the deny rule; slice 6's federation between estates.

## Effort

| Part | Size |
|---|---|
| Kernel: db/192, the five endpoints, heartbeat, Settings → Desks → Memory, the proof | M (as slice 3's kernel half) |
| maluos-memory 0.1.0: the face, the engine binding, the envelope gate, the CLI, the local test | L |
| maluos-estate 0.5.0, maluos-desk 0.8.0, the mock's memory contract | M |
| maluos-agent 0.6.0, maluos-agents 0.4.0, session and fork strings | S |
| The boot test's ten steps, both profiles, the image chain | M |
| Replication (decision 9) | S, drop first |

The order: the kernel half for approval first (as slices 1 to 3), then
the face with its local test, then the estate and desk halves against
the mock, then the image chain.
