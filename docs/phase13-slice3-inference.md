# Phase 13 slice 3: shared inference across the estate (G4 / D3)

Specified 2026-10-28 from docs/phase13-estate.md (slice 3, decisions 2,
4, 8) and docs/phase13-shared-gpus.md (G4), on top of slice 1 (nodes and
reports), slice 1b (the overlay: every member reachable at
`NAME.internal`), slice 2 (the directory, the envelope) and G2 (the node
API, the `remote` backend kind, pairing by hand). Nothing here is built.
The owner settled the edition on 2026-10-25: G1, G2, G3 and G5's local
half are Community; **G4, the estate-wide scheduler, is the paid
`scheduler` of Phase 9**. This specification keeps that line: everything
a Community estate needs to *find and use* a shared GPU host through the
directory instead of pairing by hand is in the slice; the estate-wide
admission control, priorities and the operator's placement rules are the
`scheduler` entitlement, built as a gated part of the same code.

## What the slice delivers

A GPU host that joins the estate is, without any pairing by hand, a
backend of every desk and server the estate's policy allows. The host's
heartbeat carries its **inference facts** (the models it serves, the
lanes, the expected wait, the sharing switch and the contribution rule);
the kernel keeps them in the directory beside the agents; a desk's
enrolment answer names `endpoints.inference`, the kernel's view of the
backends this desk may use, and the desk's gateway makes a `remote` rung
of each one, keyed by the desk's own node key, reached over the overlay at
`NAME.internal`. A request that leaves the host carries the **envelope**
of slice 2 when it belongs to a delegated task, and always the calling
principal's classification, so the serving host's gate holds the
originator's ceiling. A laptop shares only when its owner is away (the
idle rule of decision 8). With the `scheduler` entitlement the kernel
also answers **placement**: which backend a class of request should go
to, estate-wide queue depth, priorities and backpressure per host, and an
operator's rules on the Estate page.

```
maluctl gateway share on|off [--when idle|always]        # as today (G1/G2)
maluctl gateway estate                                   # the backends the estate publishes to this host, their state
maluctl gateway estate refresh                           # re-read endpoints.inference now (the heartbeat does it hourly)
maluctl gateway chat "…" --model strong                  # unchanged: the scheduler picks a rung; an estate rung is one more
maluctl estate inference [--json]                        # the inference facts this node reports
maluctl office estate inference                          # (operator) every backend in the estate with queue and wait
```

## What exists to build on

| Piece | Reused as |
|---|---|
| G2: the node API (`/node/v1` status, queue, models, keys), the `remote` backend kind (`system/remote-<name>` in the vault, `X-MaluOS-Origin-*` headers, both ledgers joined), `expose`, the sharing switch enforced on the serving side (`not_shared`) | the transport and the serving side, unchanged; the directory replaces `backend add … --key` by hand |
| slice 1: the node's heartbeat and report (`gateway` part: backends, queue, expected wait, share), the node key, `maluos-estated` | the inference facts ride the heartbeat; the node key becomes the estate's inference credential |
| slice 1b: the overlay (`NAME.internal`, 100.100.0.0/16) | the address every estate rung dials; no LAN name, no port forwarding, no TLS of its own needed |
| slice 2: the directory, `GET /api/v1/estate/keys`, the envelope and `X-MaluOS-Envelope` on the ledger row | the backends table beside the agents; the envelope on a delegated task's remote calls |
| the gateway's scheduler (tiers, rungs, classes, expected wait, the sensitivity gate, `remote_allowed`, `local_only`) | unchanged; estate rungs are rows it already knows how to rank |
| maluos-session's host state (chassis, power, the owner's presence) | the idle rule's inputs |
| G5's Network and Queue tabs | the estate's backends and queue shown there |

## Decisions

1. **The directory publishes backends, the gateway still decides.** The
   kernel does not route a model call. It keeps what each node's gateway
   says it serves and publishes, per desk and per node, the list of
   backends that node may use (`endpoints.inference`); the caller's own
   gateway makes a rung per backend and its scheduler ranks them with the
   local and cloud rungs as today. Nothing a caller does changes: the same
   socket, the same classes, the same `--model`.
2. **The node key is the estate's inference credential.** Pairing by hand
   issues an inference key per desk on the GPU host; the estate instead
   lets the serving gateway accept any **estate member's node key** (a
   desk's desk token is not a key: desks get a node key at enrol in this
   slice, as slice 2 gave them a signing key) whose node the kernel lists
   as allowed. The serving gateway learns the allowed members from the
   kernel (`GET /api/v1/estate/inference/peers`, cached like the keys) and
   verifies the presented key against the member's row — a key is a
   principal `node:<ref>` on the serving host, with the class and ceiling
   the kernel's policy gives it. No key crosses the estate by hand; a
   retired member's key stops working at the next refresh (five minutes)
   and at once when the serving host hears `peers_changed` on its
   heartbeat.
3. **Over the overlay, always.** An estate rung's endpoint is
   `http://NAME.internal:11435`; the serving host's `expose --bind overlay`
   is set by the join when the overlay is on. A host without an overlay
   address (overlay off) publishes no backend to the estate: pairing by
   hand remains for it.
4. **Who may use what is the estate's policy, not the host's alone.** The
   kernel's `estate_inference_policy` says which kinds and departments may
   use which backends (default: every active member may use every shared
   backend; a desk's contribution is used by servers and the coordinator's
   agents only, never by other desks, so a laptop never carries a
   colleague's chat); the serving host's own `share` switch and contribution
   rule still gate it (`not_shared`), and its gateway policy for the
   `node:` principal caps the class and the cloud fallback (never: a host
   does not spend another host's cloud credit).
5. **The idle rule (decision 8).** A laptop with `share --when idle`
   contributes when the session reports no input for ten minutes, the lid
   open or on mains, and no media playing; the session writes
   `/run/maluos/session/idle` (a JSON file with `since`) and the gateway's
   `share_state()` reads it; the first input ends the contribution: queued
   remote calls finish, new ones are refused `not_shared` with a
   `retry_after` that other rungs honour. Desktops opt in with `--when
   always` or `idle`; servers share always (the chassis rule).
6. **The envelope on remote calls.** A call made during a delegated task
   carries `X-MaluOS-Envelope` and the classification already (slice 2);
   the forwarding gateway passes both to the serving host, which ledgers
   them, so `maluctl gateway usage --envelope ID` on the serving host
   lists what another node's task cost here. The serving gateway refuses a
   call whose classification is above the kernel's ceiling for that peer
   (`classification`), as the agent does.
7. **Placement, priorities and backpressure are the `scheduler`
   entitlement.** Community: each gateway ranks the estate's rungs by its
   own expected-wait estimate, read from `endpoints.inference` (refreshed
   hourly and on `inference_changed` in the heartbeat answer), and the
   serving side's queue and `not_shared` do the rest. `scheduler`: the
   kernel keeps the estate's live queue (each node's queue snapshot with
   the heartbeat, every 60 s, with `expected_wait_s` per lane), answers
   `POST /api/v1/estate/inference/place` (a class, a model, a sensitivity,
   a deadline → the backend to use and a lease of N seconds), lets an
   operator set rules (a department's requests to this host first; a host
   reserved for batch at night; a per-host cap) on the Estate page, and
   applies priorities (interactive before batch, an operator's rule before
   the default). A Community gateway never calls `place`; a `scheduler`
   gateway asks `place` first and falls back to its own ranking when the
   kernel does not answer within 300 ms. The entitlement is a row the
   kernel publishes in the enrolment answer (`editions`), read by the
   gateway; nothing else differs in the packages.
8. **One request id across the estate.** The forwarding gateway's call id
   travels as `X-MaluOS-Origin-Request` (G2) and the serving host's ledger
   row carries it; the kernel's task record (slice 2) lists both ids per
   model call in the provenance; the Queue tab shows a remote run with
   its origin node.
9. **Three-machine proof, step 3.** The desk's personal agent asks the Help
   Desk agent on the office server; that agent asks a technical agent on
   the server, whose model call is served by the inference node's GPU over
   the overlay: three ledgers, one envelope id, one origin request id per
   hop.

## Contract (surface 1), the kernel half for approval

- **db/191**: `estate_inference` (one row per node: `models jsonb`
  (name, family, size, loaded), `lanes jsonb`, `queue jsonb`,
  `expected_wait_s jsonb`, `share boolean`, `contribution text`,
  `exposed_at inet` (the overlay address), `port int`, `api_version`,
  `updated_at`, `version bigint`); `estate_inference_policy` (rules:
  `subject` = org | dept:N | kind:desk|server|inference | node:ID,
  `backend_location_id` or null = any, `allow boolean`, `max_class`,
  `priority int`, `note`); `estate_inference_version` bumped on any
  change; `locations.node_key_public` for desks (a node key per desk,
  made at enrol and stored like the signing key); a `peers_changed` and an
  `inference_changed` flag on heartbeat answers (computed from versions
  the member last saw, as `overlay_changed` is).
- `POST /api/v1/estate/heartbeat` takes `inference: {models, lanes,
  queue, expected_wait_s, share, contribution, port}` (from the gateway's
  status, ≤ 8 KB); the answer carries `inference_changed` and
  `peers_changed`.
- `GET /api/v1/desks/inference`, `GET /api/v1/estate/inference` (a desk
  or node token): the backends the caller may use: `[{node, name,
  address, port, models, expected_wait_s, share, contribution, class_max,
  version}]`, filtered by the policy, the sharing switch and an overlay
  address present.
- `GET /api/v1/estate/inference/peers` (node token, a serving host): the
  members allowed to call this host: `[{node, kind, name, node_key_public,
  class_max, classification_max, priority}]`.
- `POST /api/v1/estate/inference/place` (`scheduler` only): `{class,
  model, sensitivity, deadline_s, origin}` → `{backend, lease_s, reason}`
  or `{backend: null, reason: "no_capacity"|"not_entitled"}`.
- Settings → Estate: the Inference tab (every backend with its models,
  queue and wait; the policy rules; with `scheduler`, the live estate
  queue and the rules editor).
- proof `bin/test_estate_inference.php`.

## The host half

- **maluos-gateway** (0.6.0): the inference facts for the heartbeat
  (`/v1/maluos/status` already has them; one `inference` summary route);
  the `estate` backend kind (a `remote` whose endpoint and key come from
  the directory: the rung dials `NAME.internal`, authenticates with this
  host's node key read from the vault as `host:<name>/estate-node-key`'s
  sibling `estate-node-token`? — no: a dedicated **node key for
  inference** `estate-inference-key`, minted by the kernel at join/enrol
  and stored beside the node token, so the token never leaves the vault
  for a network call); `maluctl gateway estate [refresh]`; the serving
  side accepts estate peers' keys (`node:<ref>` principals, the peers
  cache `/run/maluos/estate/peers.json`), applies the kernel's ceiling,
  refuses `classification`; the idle file in `share_state()`; the
  `scheduler` client (`place` with the 300 ms fallback, the lease); the
  Queue tab's remote runs with their origin.
- **maluos-estate** (0.4.0): the inference facts in the heartbeat (from
  the gateway's status), `inference_changed` → `maluctl gateway estate
  refresh` through the gateway's reload socket, `peers_changed` → the
  peers cache refreshed; the inference key stored at join; `maluctl estate
  inference`; the mock office's inference contract (`/mock/inference`).
- **maluos-desk** (0.7.0): the inference key at enrol; `endpoints.inference`
  read with the heartbeat; `maluctl office estate inference` (operator).
- **maluos-session** (0.11.0): the idle file (no input for ten minutes,
  lid, power, media), `host.idle` in the state; the Queue tab's data.
- **maluos-system-monitor** (49.1+maluos.4): the Estate page's backends
  and (with `scheduler`) the live queue and the rules.
- **maluos-firstboot**: `maluctl update` unchanged; the `editions` row in
  the provisioning state read from the enrolment answer.

## Test (tests/qcow2-boot-test.sh, both profiles, after slice 2's steps)

1. The node's heartbeat carries `inference` (the mock backend's model,
   lanes, queue, share on); the mock's `/mock/inference` shows it with the
   overlay address.
2. On the desktop: the desk's `endpoints.inference` lists `test-node`;
   `maluctl gateway estate` shows the rung `estate:test-node` at
   `test-node.internal:11435`, healthy; `maluctl gateway chat … --model
   office-estate` is served by it (a forwarded call: the desk's ledger row
   names the backend, the node's row names `node:desk:41` and the origin
   request; the same id in both).
3. `sudo maluctl gateway share off` on the node → the rung turns
   `not_shared`, the next call takes the local mock; `share on --when
   idle` with a fake idle file → shared again; writing an input mark ends
   it.
4. A delegated task (slice 2's helper) whose model call went to the estate
   rung: `maluctl gateway usage --envelope ID` lists the row on the
   serving side.
5. A classification above the peer's ceiling: refused `classification` on
   the serving side, the forwarding gateway skips the rung.
6. The mock publishes `editions: [scheduler]`; `place` answers the mock
   backend with a lease; the gateway's route carries `reason: placed`;
   without the entitlement the route carries `reason: ranked`.
7. Leave: the rung disappears from the desk's gateway within a heartbeat;
   the node's peers cache no longer lists the desk.

The three-machine proof then runs step 3 on real hosts.

## Deferred

- Multi-hop forwarding (a desk → the office server → the GPU host): never;
  G2's no-chains rule stands; the kernel's `place` points straight at the
  serving host.
- Model pulls on demand across the estate (a desk asking a host to pull a
  model): later; the operator pulls on the host.
- Billing of shared GPU time between departments: the ledger rows carry
  the origin node and the envelope; the statement is slice 5's.
- Non-MaluOS nodes (G3's node service on the Mac and the DGX Spark) as
  estate backends: when G3 ships the same `/node/v1`, the kernel lists
  them as `inference` members joined by the Sovereign LLM Manager.

## Effort

| Part | Size |
|---|---|
| the kernel half (db/191, the four endpoints, the policy, the Inference tab, `place`) | L |
| maluos-gateway: the estate rung, the peers on the serving side, the idle rule, the scheduler client | L |
| maluos-estate and maluos-desk: the facts, the keys, the refreshes, the mock | M |
| maluos-session: the idle file; the fork's Estate page | M |
| the boot test | M |

Larger than slice 2 on the gateway side; two build-and-test rounds. The
owner's decisions needed first: (a) desks get an inference key at enrol
(decision 2); (b) a desk's contribution is never used by other desks
(decision 4); (c) the idle rule's thresholds (decision 5); (d) the
`scheduler` boundary exactly as decision 7 draws it.
