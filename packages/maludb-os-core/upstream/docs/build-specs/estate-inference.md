# Shared inference across the estate (db/191) — the kernel half of Phase 13 slice 3

Built 2026-10-29 from the MaluOS specification `docs/phase13-slice3-inference.md` (maluos repository), on top of
the nodes (db/188), the overlay (db/189) and the directory (db/190). Proof:
`BOS_INTERNAL_URL=http://127.0.0.1:8089 php bin/test_estate_inference.php` (58 checks, re-runnable).

## What it does

A GPU host that joins the estate is, without any pairing by hand, a backend of every desk and server the estate's
policy allows. Each member's heartbeat carries its gateway's **inference facts** (the models it serves, the lanes,
the queue, the expected wait per class, the sharing switch and the contribution rule); the kernel keeps them and
publishes, per member, the **backends** it may use (`endpoints.inference`: the overlay name and address, the port,
the models, the wait, the ceilings the policy gives it) and, per serving host, the **peers** allowed to call it.
The kernel never routes a model call: the member's own gateway makes a rung per backend, dials `NAME.internal`
over the overlay and ranks it with its local and cloud rungs. The member's **inference key** is the estate's
inference credential: a bearer secret minted at join or enrol (and on request), shown once, only its SHA-256 kept;
the peers answer carries each peer's hash, so a serving host verifies a presented key against it and no key crosses
the estate by hand. **Who may use what is the estate's policy**: the default lets every active member use every
shared backend at an `internal` ceiling; a desk's contribution is used by servers and the coordinator only, never by
other desks, whatever the rules say (decision 4). With the **`scheduler` entitlement** (Phase 9; a flag on the
settings row until the contracts service sets it, flipped by a super-admin under Settings → Desks) the kernel also
answers **placement** from the live queue.

## Schema (db/191, additive)

| Table or column | Holds |
|---|---|
| `estate_inference` | one row per member that reported facts: `models jsonb` [{name, family, size, loaded, backend}], `lanes`, `queue` {queued, running}, `expected_wait_s` {class: s}, `share`, `contribution` always/idle, `port`, `api_version`, `signature` (what the published view depends on), `updated_at` |
| `estate_inference_policy` | the rules: `subject` org / dept:N / kind:desk|server|inference / node:ID, `backend_location_id` (null = any), `allow`, `max_class`, `max_classification`, `priority`, `note` |
| `estate_inference_settings` | one row: `version` (the backends), `peers_version` (the peers), `scheduler`, `lease_s` |
| `locations.inference_key_hash` | SHA-256 of the member's inference key (desks and nodes) |
| `locations.inference_seen_version`, `peers_seen_version` | what the member last heard (the heartbeat flags) |

## Contract additions (app/features/estate/inference.php)

| Endpoint | Token | Answer |
|---|---|---|
| `POST /api/v1/estate/join`, `POST /api/v1/desks/enroll` | code | `+ inference_key` (once), `endpoints.inference`, `endpoints.inference_peers`, `editions` |
| `POST /api/v1/estate/heartbeat`, `POST /api/v1/desks/heartbeat` | node / desk | takes `inference: {models, lanes, queue, expected_wait_s, share, contribution, port, api_version}` (≤ 8 KB, 400 over); answers `inference_changed`, `peers_changed` |
| `GET /api/v1/estate/inference`, `GET /api/v1/desks/inference` | node or desk | `{self, backends: [{node, id, kind, name, display_name, address, port, api_version, models, expected_wait_s, queue, share, contribution, class_max, classification_max, priority, updated_at}], editions, place, lease_s, refresh_s 3600, version}`; never the caller itself; only shared, online members with an overlay address; filtered by the policy. `?all=1` from an operator's desk: every published backend, each with `allowed` (`maluctl office inference --all`) |
| `GET /api/v1/estate/inference/peers` | node or desk (a serving host) | `{self, peers: [{node, id, kind, name, display_name, address, key_hash, class_max, classification_max, priority}], refresh_s 300, version}` |
| `POST /api/v1/estate/inference/key`, `POST /api/v1/desks/inference/key` | node or desk | a new key, shown once (a member enrolled before db/191, or a rotation); the old one stops at once and the serving hosts hear `peers_changed` |
| `POST /api/v1/estate/inference/place` | **an inference key** | `{class, model, sensitivity, deadline_s, origin}` → `{backend, class, expected_wait_s, lease_s, reason: placed}` or `{backend: null, reason: not_entitled | no_backend | no_model | classification | no_capacity}` |

The versions: a member's facts bump `version` only when the published view changes (a model, the switch, the
contribution, the port), never for the queue or the waits alone; a rule, a key, a join or a retirement bump both.
A read of the backends or the peers marks that version heard, so the next heartbeat's flag is false.

**The policy's precedence**: the most specific subject wins (node:ID 3 > dept:N 2, a desk's owner's departments >
kind:K 1 > org 0); at the same depth a rule naming one backend beats one for any; then a deny beats an allow. The
rule's `max_class` is the gateway class ceiling the serving host applies (a higher class is served as the
ceiling's), `max_classification` the sensitivity above which the serving host refuses `classification`,
`priority` ranks the backend (the scheduler places there first; a caller's gateway may rank by it).

**Placement** considers the allowed, published backends that serve the model, refuses the classification above the
rule's ceiling, skips a host with 100 or more queued or whose wait for the class is past the deadline, and takes
the highest priority then the lowest expected wait. Without the entitlement every call answers `not_entitled`.

## Departures from the MaluOS text, and why

1. **The peers answer carries the key's SHA-256, not a public key.** The slice's host half settled on a dedicated
   bearer inference key beside the node token (so the token never leaves the vault for a network call); G2's
   transport is a bearer header and stays unchanged. The hash is enough for the serving side to verify a key and
   leaks nothing.
2. **`place` authenticates with the inference key**, not a node or desk token: the gateway calls it on every
   request and holds the inference key for its rungs already; the node token stays in the vault.
3. **The entitlement is a flag on `estate_inference_settings`**, flipped under Settings → Desks, until Phase 9's
   contracts service exists; the join and enrol answers and `endpoints.inference` publish it as `editions`.
4. **Settings → Desks, not a new Estate page**: the Inference section joins the overlay and delegation sections
   there (`present_inference_for_settings()`; `html/settings/desks/inference.php` for the entitlement and the rules).
5. **Desks report facts too** (a laptop that shares while idle): the desk heartbeat takes `inference` and the
   peers endpoint takes a desk token, since a sharing desk is a serving host.

## Where it lives

`db/191_estate_inference.sql`; `app/features/estate/inference.php` (loaded by `desks.php`, so every estate
endpoint has it); `html/api/v1/estate/inference.php` (`?sub=peers|key|place`), `html/api/v1/desks/inference.php`;
the heartbeat, join and enrol endpoints; `node_retire()` / `desk_retire()` → `inference_member_retire()`;
`html/settings/desks/inference.php`; `web/components/settings/MySettings.tsx` (`Inference`) and
`web/lib/schemas/settings.ts`; `docs/deploy/apache-react-cutover.conf` (the allow-list).
