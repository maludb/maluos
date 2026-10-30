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
   kernel does not answer within the placement timeout (1.5 s by default,
   `MALUOS_PLACE_TIMEOUT_S`). The entitlement is a row the
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
  `scheduler` client (`place` with the timed fallback, the lease); the
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

## Status

**Both halves built 2026-10-29** on the spec's recommendations (the owner's
word: "using the spec's recommendations" for the four decisions of the
Effort section: desks get an inference key at enrol; a desk's contribution
is never used by other desks; the idle rule's thresholds as decision 5
writes them; the `scheduler` boundary exactly as decision 7 draws it). The
image chain and the boot tests of both profiles follow; the result is
appended under "What the image chain found" at the end of this section.

- The kernel half (maludb-os-core d7ebcfa, vendored as maludb-os-core
  2026.10.29maluos1; `docs/build-specs/estate-inference.md` there): db/191
  (`estate_inference` per member, `estate_inference_policy`,
  `estate_inference_settings` with the two versions and the `scheduler`
  flag, `locations.inference_key_hash`); the inference key minted at join
  and enrol, shown once; the facts on both heartbeats with
  `inference_changed` and `peers_changed`; `GET …/inference`,
  `GET …/inference/peers`, `POST …/inference/key`, `POST
  …/inference/place`; the policy's precedence; Settings → Desks gains the
  Shared inference section (the backends, the rules editor, the
  entitlement switch); proof `bin/test_estate_inference.php` (58 checks).
- The host half: maluos-gateway 0.6.0 (`maluos_gateway.estate`: the
  `estate` backend kind from the directory's cache, the peers cache on the
  serving side, the ceilings, the idle rule's refusal with `retry_after`,
  the scheduler client with the timed fallback, the envelope on
  forwarded calls, `GET /v1/maluos/inference`, `maluctl gateway estate
  [refresh]`, `chat --prefer estate`), maluos-estate 0.4.0 (the facts on
  the heartbeat, the caches under `/run/maluos/estate`, the key at join
  with a `use` grant to the gateway, `maluctl estate inference`, the mock's
  whole contract), maluos-desk 0.7.0 (the key at enrol, the facts on the
  desk heartbeat, the caches under `/run/maluos/office`, `maluctl office
  inference [--all] [--new-key]`), maluos-session 0.11.0 (the idle rule
  measured every 30 s from Mutter's idle monitor, UPower and MPRIS; the
  mark `/run/maluos/session/idle`; `host.idle`; `gateway.estate` for the
  Network tab), maluos-firstboot 0.1.12 (`maluos_gpu.share_state` applies
  the idle rule), maluos-system-monitor 49.1+maluos.5 (the estate's
  backends in the Network tab's Paired Nodes group).
- Tests: tests/gpu-test.py (the idle rule in `share_state`),
  tests/gateway-local-test.sh (an estate rung to the host's own listener
  from a hand-written directory cache: the forwarding loop, both ledger
  rows, the envelope, the tier, the ceilings, cloud never, the class cap,
  `not_shared` with the idle mark, placement against a fake kernel:
  placed, ranked on a slow answer, plain in Community; 188 checks in all),
  tests/desk-local-test.sh (the mock's contract end to end with a fake
  gateway socket: the facts on both heartbeats, a fake GPU host published,
  the caches, the policy flags, the entitlement, placement, key
  rotation; 133 checks in all), tests/qcow2-boot-test.sh (the seven steps
  of the test plan above: the node side on both profiles with a fake peer
  calling over the overlay; the loop on one machine on the desktop, where
  the host is both the desk and the node).
- docs/phase13-three-machine-proof.md: the runbook of D7 for the owner's
  three machines (office, gpu, desk), slices 1 to 3 on real hosts.

Where the build departs from the text above, and why:

1. **The inference key is a bearer secret and the peers answer carries its
   SHA-256**, not a public key: the host half's own choice above (a
   dedicated key beside the node token, so the token never leaves the
   vault for a network call) keeps G2's transport as it is; the hash is
   enough for the serving side and leaks nothing. `place` authenticates
   with that key too, since the gateway holds it already.
2. **The entitlement is a flag on the kernel's settings row**, flipped
   under Settings → Desks by a super-admin, until Phase 9's contracts
   service exists; the join and enrol answers and `endpoints.inference`
   publish it as `editions`, and the member's enrolment file keeps it.
   maluos-firstboot's provisioning state is not touched.
3. **The caches, not a socket**: the enrolment side (the daemon for a
   node, `maluctl office` for a desk) writes the directory's answer to
   `/run/maluos/estate/inference.json` and `peers.json` (a desk under
   `/run/maluos/office`, trusted only when root or the owner wrote it);
   the gateway reads them at every catalogue reload. A host that is both
   a node and a desk holds both views and the gateway merges them, each
   rung with its own membership's key; the boot test's one-VM loop rests
   on that.
4. **The estate rung dials the overlay address**, not `NAME.internal`:
   the same thing without a hosts-block race; the name stays on the rung
   for the eye.
5. **Settings → Desks, not an Estate page** in the kernel: the Inference
   section joins the overlay and delegation sections there.
6. **`maluctl gateway estate refresh`** runs `maluctl estate inference
   --refresh` or `maluctl office inference --refresh` (whichever
   membership the host has), then a reload: the gateway itself holds no
   office token.
7. **The idle rule's measurement lives in the session service** (Mutter's
   idle time, UPower's lid and battery, MPRIS), not in the shell
   extension; a server session has none, so a server's `--when idle`
   stays off until a session says idle. The boot test proves the mark on
   the desktop, where the session has had no input since login.
8. **`X-MaluOS-Prefer: estate` is a preference**, like `cloud` and
   `local`: with no eligible estate rung the call takes the local or cloud
   rung; `maluctl gateway chat --prefer estate` says so in the route.
9. **The kernel's placement call has its own client session** in the
   gateway: the shared session stalled its first request to a new host
   for the whole placement timeout (found by tests/gateway-local-test.sh), and the
   kernel's traffic should never queue behind a backend's pool.

### What the image chain found (2026-10-29, the desktop UEFI boot test, first run)

The first run of the chain failed nine slice 3 checks on the desktop, none
of them in the kernel. Fixed before the second run:

- **The placement timeout was 300 ms.** On the TCG test VM the mock
  office answered too late and every placed call fell back to the
  gateway's own ranking. The default is now 1.5 s
  (`MALUOS_PLACE_TIMEOUT_S`): the kernel is a PHP request over the
  overlay, and a model call takes seconds anyway; a late or missing answer
  still falls back to ranking.
- **The session counted the estate's rungs as paired nodes.** The session's
  `node.paired` is the gateway's remote backends; the estate rungs are
  remote too, so the Network tab's summary said "2 paired". They are
  `gateway.estate.backends` now and only there.
- **The idle mark flapped under load.** The session's idle thread read the
  idle time from Mutter with a 3 s D-Bus timeout; while gnome-shell was
  busy with the GUI self-tests the read timed out, the thread took that
  for input and removed the mark, so the serving side refused
  `not_shared` in the middle of the loop. A failed measurement now holds
  the last decision (the lid, the battery and the media still count), the
  timeout is 10 s, and the test prints the idle journal for evidence.
- **Placement on a host with two memberships asked with the wrong key**
  (second run). A host that is both a desk and a node holds two inference
  keys and two views: the desk may use the servers, the node may use the
  desk's contribution. The gateway asked the kernel to place with the
  first key it found (the node's), the kernel answered the desk's own
  contribution, and the call went to that rung instead of the server's.
  The gateway now asks as the membership whose rung ranks first and lets
  the kernel choose among that membership's rungs only; unhealthy rungs
  rank last, so a placement is never made for a rung the gateway would
  skip.
- **The test itself**: the node's facts are read after the listener is up
  (the facts carry the listener's port, which slice 2 had left at 11436);
  the session's view of the share switch is polled (it reads the gateway
  every 20 s); the desktop loop starts with the switch on `--when always`
  and tests the idle rule explicitly in its step 3; both caches (the
  node's and the desk's, one host) are refreshed when the entitlement
  flips; the restricted check reads the ledger's route as the gateway
  suite does (`--prefer estate` is a preference: the person's own egress
  policy skips the rung first and the call is served locally; with egress
  widened the kernel's ceiling skips it as `classification`).

The third run left one failure, a race in the test (the idle mark removed
by hand stands for input, but the session has seen none and puts it back
within its 30 s poll; the check now tries three times). The fourth run,
both UEFI boot tests on the images built at 23:20 (the final packages),
passed on 2026-10-30: desktop 389 checks, server 191 checks, the slice 3
steps of both profiles among them. The System Monitor's local suite gained
a case with two estate backends (one not shared, the scheduler on), and
lintian is clean on the seven packages apart from a pre-existing override
in the vendored kernel package.

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
