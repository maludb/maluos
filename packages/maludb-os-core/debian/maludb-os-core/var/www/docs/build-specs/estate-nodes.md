# The estate's nodes — the kernel half of Phase 13 slice 1 (db/188)

Built 2026-10-28 from the MaluOS specification docs/phase13-slice1-nodes.md
(maludb/maluos), approved by the owner the same day. That document is the
contract; this page says what landed here.

## What it is

A MaluOS server or inference host joins the estate the way a desk does
(db/187): an operator (a super-admin) mints a one-time node code in
Settings → Desks (or `php bin/mint_desk_code.php --email … --kind server`),
the host exchanges it at `POST /api/v1/estate/join` for a node token, then
heartbeats every 60 s with its facts and, every 300 s, a report (units,
agents, the gateway, vault alerts, updates, disk, memory, load). The kernel
applies fixed health rules to each report and keeps the estate's alerts;
desks whose owner is an operator read the whole estate.

## Schema (db/188, additive)

- `locations.kind` gains `server`, `inference`; `report jsonb`,
  `last_report_at`, `public_key`, `enrolled_by_member_id`, `components`.
- `mcp_access_tokens.scope` gains `node` (one live per node, bound to its
  location); `mcp_resolve_token()` skips node tokens, so the MCP servers
  never read a node as a person.
- `desk_enrollment_codes.kind` (`desk` | `server` | `inference`): a desk
  code enrols only a desk, a node code only a node of its kind.
- `estate_node_reports` (24 kept per node), `estate_alerts` (one open row per
  node, kind and subject; cleared when the next report no longer shows the
  cause; `node_offline` from presence).
- `activity_log.source` gains `node`.

## Endpoints (`html/api/v1/estate/`, `html/api/v1/desks/estate.php`)

join (the code), heartbeat, me, leave (bearer node token), nodes and
nodes/ID (bearer node token, or a desk token whose owner is an operator;
403 otherwise). `endpoints.estate` is published on a desk's answers when
its owner is an operator and is null otherwise. Apache: the three
`estate` rewrite lines in docs/deploy/apache-react-cutover.conf.

## The rules

offline → `offline`; a unit of the fixed list down, an agent failed or
failing, a vault alert, the gateway not answering, a restart required,
disk over 85 % → `warning`; PostgreSQL or the vault down, disk over 95 %,
memory under 5 % → `critical`. app/features/estate/nodes.php.

## Presence

bin/cron/desk_presence.php now runs every minute and sweeps nodes too: a
node silent for three heartbeats is offline, with `node_offline` raised.

## Settings

Settings → Desks for an operator carries the estate's nodes with their
health and the open alerts, and mints node codes with a kind
(MySettings.tsx, `estate` in the settings JSON). Work Locations lists
servers and inference nodes beside buildings, offices, desks and sites.

## Proof

`BOS_INTERNAL_URL=http://127.0.0.1:8089 php bin/test_estate_nodes.php`
(54 checks); `bin/test_desk_enrolment.php` still passes.

## Deploy

`db/188` as postgres; the Apache lines and a reload; the crontab (every
minute); `npm run build`. A MaluOS office picks all of it up when the
kernel package is re-vendored at this commit.

## Not in this slice

Actions on remote nodes (slice 2, with the envelope), the overlay
(slice 1b, db/189), node-to-node traffic (slice 3).
