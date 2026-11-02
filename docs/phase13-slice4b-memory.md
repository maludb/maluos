# Phase 13 slice 4b: memory quality

Built from 2026-11-01 on slice 4 (docs/phase13-slice4-memory.md), at the owner's
word ("go back to your initial set of recommendations and work on those"). Three
pieces, the first two of the recommendation and a follow-up from slice 4's
finding 7; the third recommendation, the three-machine proof, is the owner's to
run (docs/phase13-three-machine-proof.md).

## 1. Semantic recall: embeddings on the host

What slice 4 left: recall is PostgreSQL full-text search over title and
summary, so "what do we know about forklift training" finds the words, not the
meaning. The engine (maludb-core 0.106.0) never computes a vector and cannot
call an embedder from SQL, but its rail is there: `malu$object_embedding` takes
`object_kind = 'memory'` in any dimension, each tenant has
`maludb_register_object_embedding()` and `maludb_semantic_search()`, both open
to the face's role through `grant_memory_access(role, 'write')`, and the search
applies the memory's principal policy as the invoker. The maludb-api's hash
vectors (a sha256-seeded unit vector when no embedder is configured) are not
used: they rank at random and would contaminate a space shared with real
vectors.

Decisions (mine, stated here for the owner):

1. **The face embeds through the gateway**, over its Unix socket, as
   `user:maluos-memory` (the principal first boot creates), with the OpenAI
   face `POST /v1/embeddings {model, input}`. Every embedding is a model call
   in the gateway's ledger like any other; the gateway routes it to the
   backend that has the model (Ollama, an estate node later). Every call
   carries the texts' highest classification (`X-MaluOS-Sensitivity`), so the
   gateway's egress policy and the rungs' ceilings apply to it: a restricted
   note is embedded on this host or not at all, and the backfill batches by
   classification.
2. **One model per space.** The space is `memory/<model>`; changing the model
   is a new space, and the search filters by space and dimension, so old
   vectors never mix with new ones and a host can switch a model on later and
   backfill without a migration. The text embedded is `title + summary`, the
   same text the full-text search indexes.
3. **Recall is the union of semantic and text hits.** With a model: the query
   vector → `maludb_semantic_search(k = 3 × limit, space)` → the ids whose
   score is at least `min_score` (0.35 by default; nomic-embed-text's cosine)
   → re-selected through the `maludb_memory` view with the same scope,
   ceiling, kind and tombstone filters as today (so the policy, and a
   forgotten memory's vector, are handled by the view) → union with the
   full-text hits, semantic first by score, then text by rank. A claim says
   which it was: `match: semantic | text` and `score`. Without a model, or when
   the embedder fails or times out, recall is exactly slice 4's.
4. **Writes register the vector in the same transaction** as the insert
   (`remember`, and `sync_write` for replicated copies); when the embedder
   does not answer, nothing is written and the memory is found by text until a
   backfill. `maluctl memory embed` backfills what lacks a vector in the
   active space.
5. **Configuration**: memory.yaml `embed: {model, url, timeout_s, min_score}`;
   `maluctl memory embed MODEL [--pull]` sets the model (and pulls it through
   `maluctl gateway ollama pull` when asked), `--off` clears it, `--status`
   counts what is embedded; `maluctl memory status` and the facts show it.
   First boot: `components.maluos-memory.embed: {model: nomic-embed-text,
   pull: true}` in firstboot.yaml, an option, not a default: a host without a
   model keeps text recall, and nothing is pulled unasked.

## 2. The Memory MCP published to desks

What slice 4 left: `endpoints.memory` is the holders view and the desk asks
the office with `POST /api/v1/desks/memory/query`; the kernel's Memory MCP
(port 8814: `recall`, `core_memory`, `session_search`) is not proxied, and if
it were, it could not tell a desk's token from a person's: `mcp_resolve_token`
maps any live non-node token to its member, and the MCP would answer a desk
from the owner's whole department set, outside the estate policy of db/192.

Decisions:

6. **Proxied like the others**: `/mcp/memory` → 127.0.0.1:8814 in both Apache
   files; `endpoints.memory_mcp` at enrol, heartbeat and me; `memory` keeps
   its meaning (the holders view).
7. **The desk path applies the estate policy by relaying**: db/193 gives the
   resolver the token's `scope` and `location_id`; the MCP keeps them in the
   request context; `recall` from a desk token calls the office's own
   `POST /api/v1/desks/memory/query` with that bearer and maps the tool's
   scope (`self`, `department`, `org`, or all) onto the office's scopes for the
   desk (`GET /api/v1/desks/memory` → `office.scopes`). One policy, one rate
   limit, one `memory.query` row, the same answer the CLI gets. `core_memory`
   and `session_search` already narrow to the owner and the agents they
   manage; a desk's token acts as its owner there, as the records and
   activity MCPs do.
8. **On the desk**: office.env carries `MALUOS_OFFICE_MEMORY_URL` (the holders
   view; the Agents app used `MALUOS_OFFICE_MEMORY_MCP` for it since slice 4)
   and `MALUOS_OFFICE_MEMORY_MCP` (the MCP, when the office publishes one);
   `maluctl office status` lists it. An agent that holds the desk token
   (`maluctl secret grant office-desk-token --to agent:NAME`) reaches it as it
   reaches the records MCP. The mock office serves `/mcp/memory` with a `recall`
   tool over its office memory under its policy, so the boot test proves the
   contract end to end.

## 3. A host with two memberships is published once

Slice 4's finding 7: the office allocates a desk its own overlay address at
enrolment, which a desktop that is also a node never carries (its one
interface is the node's). The directory published such a desk as a holder at
that dead address.

9. **A desk whose machine id is an active node's is not a memory holder**; its
   face is the node's and is published as the node (every department, the
   server policy). Settings → Desks says why ("the node X of the same host").
   Both memberships still record a machine id (db/187 for desks, db/188 for
   nodes: the sha256 of /etc/machine-id). The mock does the same, and the boot
   test's one-host proof asks the node identity alone through the desk's cache
   (the local test keeps both keys).

## Versions

maluos-memory 0.2.1, maluos-desk 0.9.0, maluos-agents 0.5.0, maluos-estate
0.6.0 (the mock), maluos-gateway 0.6.1 (the mock Ollama's embeddings),
maluos-firstboot (the component's option) as listed in the Status; the kernel
at db/193 (maludb-os-core), vendored as 2026.11.01maluos1.

## Status

Built 2026-11-01 (the kernel half committed as maludb-os-core ab00263, the
host half uncommitted in this tree until the image chain passes).

- **Kernel (db/193, ab00263)**: `mcp_resolve_token()` answers `token_scope`
  and `location_id`; the MCP middleware keeps them with the raw bearer; the
  Memory MCP's `recall` from a desk token relays to the desks memory
  endpoints (`mcp/memory_server.py`); `/mcp/memory` proxied in both Apache
  files; `endpoints.memory_mcp`; a desk whose machine id is an active node's
  is not a holder (`memory_holder_is_other_membership()`), Settings → Desks
  says why. Proofs: `bin/test_estate_memory.php` 74 checks,
  `bin/test_memory_mcp_desk.py` 9 (the relay against a fake office, no
  Postgres), `bin/test_desk_enrolment.php` (its endpoint check brought up to
  db/192 and db/193: it had asserted `memory: null` since db/192 and failed),
  `bin/test_estate_nodes.php`. Vendored as maludb-os-core 2026.11.01maluos1.
- **maluos-memory 0.2.1**: `Embedder` (the gateway's OpenAI face over its
  socket as `user:maluos-memory`, or a URL: `…/v1/embeddings` OpenAI-shaped,
  `…/api/embed` Ollama-shaped), `register_vector()` on the engine's rail
  (`maludb_register_object_embedding`, provenance `provided`, space
  `memory/<model>`), `semantic_ids()` (`maludb_semantic_search`, cosine, at or
  above `min_score`), `recall()` as the union re-read through the facade
  (`match`, `score` on every claim), vectors with `remember()` and the
  replicated copies, `embed_status()`, `backfill()` (the keeper's hourly
  pass too); `GET/POST /v1/embed`; `maluctl memory embed` (set with `--pull`
  and `--url`, `--backfill`, `--probe`, `--off`, the status); `maluctl memory
  status` shows the model; first boot's `components.maluos-memory.embed`.
  The ledger: `memory.embed` rows for the probe and the backfill, counts only.
- **maluos-gateway 0.6.1**: the mock Ollama's embeddings are a synonym-aware
  bag of words over 256 dimensions (forklift and lift truck, training and
  certification, …) so the tests prove recall by meaning; the gateway test's
  dimension checks follow.
- **maluos-desk 0.9.0 / maluos-agents 0.5.0 / maluos-estate 0.6.0**:
  office.env `MALUOS_OFFICE_MEMORY_URL` (the holders view) and
  `MALUOS_OFFICE_MEMORY_MCP` (the MCP); `maluctl office status` lists
  `memory_mcp`; the Agents app queries beneath the holders view; the mock
  office publishes `memory_mcp`, serves `/mcp/memory` with a `recall` tool
  under its policy, and applies decision 9 to its holders.
- **Tests**: `tests/memory-local-test.sh` 70 checks (a semantic section: the
  model set against the mock Ollama's `/api/embed`, nothing embedded before
  the backfill, "lift truck certification" finds the forklift note by
  meaning with its score and never the restricted note, a write carries its
  vector, the scope filter holds over semantic hits, the embedder gone leaves
  text recall and a write without a vector, `--off`);
  `tests/desk-local-test.sh` 149; `tests/agent-tasks-test.py`;
  `tests/gateway-local-test.sh` 188; the boot test's slice 4 block gains the
  gateway path (`embed mock-embed` probed through the socket, the backfill,
  recall by meaning, the gateway's ledger rows by `user:maluos-memory`), the
  Memory MCP's `recall` tool with the desk token at the mock, office.env and
  `maluctl office status`, and the one-host proof asks the node identity
  alone (decision 9). The image chain (packages with lintian, the local
  repository, both images and ISOs, both UEFI boot tests) passed on its eighth
  run, 2026-11-02 00:29 UTC: desktop 445 checks, server 200, no failures
  (runs 6 and 7 are the finding below).
- **Found on the way**: the engine's object-embedding rail takes a
  provenance word (`provided`, `suggested`, `accepted`, `rejected`), not a
  free label; lintian (H4) is back on in the package build, on the current
  version of every package but the kernel (34 s, 150 MB): the installer's
  two intentional errors are overridden (0.3.3), the agent changelog fixed.
- **The chain's sixth run** (2026-11-01, desktop 435 ok): the boot test's
  semantic block ran after the mock Ollama behind the gateway's mock backend
  had been stopped (slice 3's block stops it), so every embedding met "no
  eligible backend" (503): the block starts its own mock now. Reading the
  failure showed a gap: the face sent its embeddings with no classification,
  so a restricted note's text could have left the host through a cloud rung
  under the face's egress policy (internal by default). Closed in 0.2.1:
  every call carries the texts' highest classification, the boot test checks
  the restricted note's call was restricted. The same run had the dev VM
  under memory pressure (the host ballooned to 9.7 GB, swap in use): the
  desktop test took 40 minutes longer than run 5, the session lost the
  office and the gateway for minutes at a time ("reachable again" at
  18:36 and 18:44), the mock marked the node offline between two
  heartbeats; six slice 1 checks failed on timing, none on code. The slice 1
  "office.estate carries both nodes" wait now covers the node's health too.
  The seventh run (0.2.1, the evening) passed every slice 4b check and failed
  two slice 2 inbox checks the same way (the session's office poll eight
  minutes stale); the eighth, from the same images at night, passed clean.
  The session's polling under a stalled host is a robustness item for later,
  not this slice's.
