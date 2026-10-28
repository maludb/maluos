# The overlay — the kernel half of Phase 13 slice 1b (db/189)

Built 2026-10-28 from the MaluOS specification docs/phase13-slice1b-overlay.md
(maludb/maluos), approved by the owner the same day, beside db/188
(estate-nodes.md). That document is the contract; this page says what
landed here.

## What it is

Every member of the estate (server, inference, desk) sends its WireGuard
public key at join or enroll and receives an address in the estate's
private range and a name (`NAME.internal`). The hub is the coordinator's
own host, joined with `--hub HOST:PORT`; spokes keep one tunnel to it and
reach each other through it. The kernel allocates, keeps the public keys
and publishes the hub, the peers and the names; the private keys never
leave the members' vaults.

## Schema (db/189, additive)

- `estate_overlay`: one row — `enabled`, `range` (default
  `100.100.0.0/16`), `hub_location_id`, `hub_endpoint`, `hub_public_key`,
  `version` (bumped on every change).
- `locations.overlay_public_key`, `overlay_address` (kept for the member's
  life; `overlay_address_freed_at` on retirement, reused after 30 days),
  `overlay_seen_version`.

## Contract additions (app/features/estate/overlay.php)

- Join and enroll take `overlay_public_key` and (the hub's join only)
  `overlay_hub: {endpoint}`; 409 `hub_exists` while another hub is active,
  400 `invalid` for a bad endpoint; an invalid key is ignored. The answer's
  `overlay` block: `address`, `prefix`, `name`, `hub` (null for the hub),
  `role`, `listen_port`; null while no hub has joined (the address is
  allocated and kept meanwhile) or the member sent no key.
- `GET /api/v1/estate/overlay` (node token) and `GET /api/v1/desks/overlay`
  (desk token): `self`, `hub`, `peers` (the hub for a spoke; every member
  for the hub), `names`, `refresh_s` 60, `version`.
- `POST /api/v1/estate/overlay/key` (node or desk token): rotation, or a
  first key for a member that joined without one.
- Heartbeat answers carry `overlay_changed` once per change; `endpoints.
  overlay` names the GET or is null.
- Leave and retirement free the address into quarantine; a hub leaving
  unsets the hub and every spoke's `overlay` goes null until one returns.

Settings → Desks for an operator shows the overlay (range, hub, members)
and each node's address. Apache: the `overlay` rewrite lines.

## Proof

`BOS_INTERNAL_URL=http://127.0.0.1:8089 php bin/test_estate_overlay.php`
(48 checks, re-runnable: it releases its own quarantined addresses); the node and desk proofs still pass.

## Not in this slice

A mesh or NAT traversal, a second hub, IPv6, names through systemd-resolved,
automatic rotation (docs/phase13-slice1b-overlay.md, Deferred).
