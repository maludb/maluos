# Phase 13 slice 1: nodes and the operator's view

Specified 2026-10-23 from docs/phase13-estate.md (decisions 1 to 4, 9)
and the desk enrolment of Phase 12 slice 6 (docs/desk-enrolment.md),
which this slice generalises. Nothing here is built. It is sequenced
after Phase 12 slice 9 in docs/roadmap.md (D1); the kernel half needs
the owner's approval before it is built, as db/187 did.

## What the slice delivers

A MaluOS server joins the estate the way a desk joins an office today,
reports its health with every heartbeat, and a system manager sees every
node of the estate, its health and its alerts on their Desk, with a
notification when a node goes offline or an alert is raised. Read-only:
no action reaches a remote node until slice 2 brings the delegation
envelope.

```
# on a server (the coordinator's own host included)
sudo maluctl estate join https://app.example.com --code 7F3K-2Q9M [--name db-1] [--kind server|inference]
maluctl estate status [--json]
maluctl estate report [--json]
maluctl estate nodes [--json]
sudo maluctl estate leave

# on a desk: the existing enrolment is the desk's node record
sudo maluctl estate join URL --code CODE      → runs `maluctl office enroll` and says so
maluctl estate nodes [--json]                 → the office's estate as this desk's owner may see it
```

## What exists to build on

| Piece | Reused as |
|---|---|
| `maluctl office enroll|heartbeat|status|leave` and the surface 1 contract | the shape of `maluctl estate join|heartbeat|status|leave` and of the `/api/v1/estate/*` endpoints; the code is the same code moved into a shared client module |
| the kernel's `locations` (db/043) with `kind`, `presence`, `last_seen_at`, the facts columns, `machine_id` (db/187), `desk_enrollment_codes`, the presence sweep | the node directory; two new kinds, a report column, a `kind` on the codes |
| the vault's peer-credential identity and the `identities` map (Linux user → principal) | the server's node identity: a system user mapped to a `host:` principal |
| the session's `office_loop`, `office_agents_read` / `office_apps_read`, the `office.*` state and its notifications | the desk's view: `office_estate_read` after each heartbeat, `office.estate` in the state, two notifications |
| the session's `host_state`, `gateway_state`, `vault_state`, `alerts_state`, `agents_state`, `updates_state` | the server's report is the same reads, by the same code, run as the host principal instead of the person |
| the Desk window's pages (maluos-desk) | the Estate page |
| the mock office and the boot test's office section | the mock estate and the slice's test |

## Decisions

1. **Node kinds: `desk`, `server`, `inference`.** The kernel's
   `locations.kind` gains `server` and `inference` (additive, a CHECK
   change in db/188). `building` and `office` stay what db/043 made them,
   the operator's description of a hypervisor and its VMs; a server node
   is the machine's own account of itself. Linking a `server` row to the
   `office` row an operator typed for the same VM is a kernel nicety for
   later (match by hostname, offer "this is the VM you described as X").
   An `inference` node is a server whose purpose is the gateway; slice 1
   treats it exactly like a server and the kind only labels it, so that
   slice 3's scheduler has something to select on from day one.
2. **A desk's node record is its desk row.** A desk does not enrol
   twice. `maluctl estate join` on a desk calls `maluctl office enroll`
   and prints that it did; `estate nodes` on a desk uses the owner's desk
   token. Presence stays the person's (docs/desk-enrolment.md, "Presence
   is the session"); the desk's facts stay what the heartbeat sends. A
   desk sends no report in this slice: its owner's Desk already shows the
   desk's own health, and a system manager who wants a desk's report gets
   it in slice 2 with the envelope that makes the request accountable.
3. **A server's identity is a host principal.** The package creates the
   system user `maluos-estate` and maps it in `/etc/maluos/vault.yaml`
   and `/etc/maluos/gateway.yaml` (`identities`) to `host:<hostname>`; the
   vault's `maluctl principal add host:<hostname> --kind host` happens at
   `join`. The node token (`estate-node-token`, kind token, provider
   estate) and the node key (`estate-node-key`, kind key: an ed25519 key
   made with `ssh-keygen -t ed25519` at `join`, never written outside
   the vault) live in that principal's compartment. `join` runs as root
   and stores both *as `maluos-estate`* (`runuser`), so the vault's peer
   identity holds and the ledger names the host. The public key goes to
   the kernel in the join request; nothing verifies a signature until
   slice 2's envelope, which signs with this key. The key exists now so
   that slice 2 changes no enrolment.
4. **Presence on a server is "the node is up".** `maluos-estate.service`
   heartbeats every `heartbeat_s` with `presence: online` while it runs
   and sends `offline` on a clean stop (SIGTERM: shutdown, `leave`); the
   kernel's presence sweep marks a node offline after three missed
   heartbeats, as it does desks. `is_always_on` is true for servers.
5. **The report is the host's own reads, bounded, without secrets.**
   Everything in it comes from the status calls the Desk already makes on
   a desk (the session's `*_state` functions, moved to a shared module):
   units, agents, the gateway, vault alerts, updates, disk, memory, load.
   No value from the vault, no prompt text, no ledger detail beyond
   alert reasons. A report is at most 32 KB; the kernel keeps the last
   24 per node and the current one on the row.
6. **Who sees the estate is the kernel's decision.** The enrol, `me` and
   heartbeat answers to a desk carry `endpoints.estate`, a URL when the
   desk's owner holds a role the kernel maps to "system manager", `null`
   otherwise. The desk evaluates no roles: the Estate page exists when
   the endpoint does. A server's `estate nodes` is always answered (a
   node may see its peers; it is an operator who runs it).
7. **Read-only.** No restart, no update, no `leave` of another node from
   the Desk; the page offers "Open a terminal" with the `ssh` line for
   the node and nothing else. Slice 2 adds actions with the envelope.
8. **Transport is HTTPS to the coordinator only.** Nodes do not talk to
   each other in this slice. The coordinator is the kernel, reached at
   the office URL; the kernel's own host joins as a `server` node like
   any other so that it appears in its own estate.
9. **Community edition.** Joining, the report and the operator's view
   are what every estate needs to be operable; decision 10 of the phase
   plan (the paid boundary) is not touched by this slice.

## The contract, surface 1, estate endpoints

Same conventions as the desks surface: JSON over HTTPS on the office's
person face, `surface` in every request and answer, errors as
`{"error": code, "message": text}` with the HTTP status.

| Method and path | Auth | Purpose |
|---|---|---|
| `POST /api/v1/estate/join` | the code in the body | register this node; mint its token |
| `POST /api/v1/estate/heartbeat` | `Authorization: Bearer <node token>` | presence, facts and the report |
| `GET /api/v1/estate/me` | bearer | the node, its endpoints (no presence change) |
| `POST /api/v1/estate/leave` | bearer | retire the node; the token is revoked |
| `GET /api/v1/estate/nodes` | bearer (node token or desk token) | the estate as the caller may see it: nodes with health and alerts |
| `GET /api/v1/desks/estate` | bearer (desk token) | the same answer for a desk; `endpoints.estate` in the desk's answers names it or is `null` |

**Join request**

```json
{"surface": 1, "code": "7F3K-2Q9M", "kind": "server", "name": "db-1",
 "principal": "host:db-1", "public_key": "ssh-ed25519 AAAA… host:db-1",
 "hostname": "db-1", "os_platform": "linux", "os_release": "MaluOS 26.04.20261030", "variant": "Server",
 "app_version": "maluos-estate 0.1.0", "mcp_surface_version": "1",
 "cpu_cores": 16, "memory_mb": 64000, "storage_gb": 900, "machine_id": "<sha256 of /etc/machine-id, 32 hex>",
 "components": ["postgresql-18", "maludb-core", "mc2dbd", "vault", "gateway", "agent"]}
```

`kind` is `server` or `inference` (a desk never calls this endpoint);
`name` defaults to the hostname; `components` is what the host's
provisioning record says it runs (`/var/lib/maluos/provisioned.json`).
The code is minted for a kind: a desk code enrols only a desk, an estate
code only a server or inference node (`desk_enrollment_codes.kind`).

**Join answer** (201)

```json
{"surface": 1,
 "node": {"id": 57, "kind": "server", "name": "db-1", "status": "active"},
 "office": {"name": "Subello", "url": "https://app.subello.com"},
 "enrolled_by": {"member_id": 1, "email": "ed@example.com", "display_name": "Edward Honour"},
 "token": "node_…",
 "endpoints": {"heartbeat": "…/api/v1/estate/heartbeat", "me": "…/api/v1/estate/me", "leave": "…/api/v1/estate/leave",
               "nodes": "…/api/v1/estate/nodes"},
 "heartbeat_s": 60, "report_s": 300}
```

The token is shown once. `report_s` says how often the full report is
wanted; heartbeats between reports carry presence and facts only, so a
60-second heartbeat does not cost a status read of the whole host every
minute. Errors: 400 `invalid`, 403 `bad_code` (unknown, expired, used, or
minted for another kind), 409 `name_taken`.

**Heartbeat request** (bearer)

```json
{"surface": 1, "presence": "online", "app_version": "maluos-estate 0.1.0",
 "facts": {"hostname": "db-1", "os_release": "…", "cpu_cores": 16, "memory_mb": 64000, "storage_gb": 900},
 "report": { … see below, or absent … }}
```

**Heartbeat and me answer** (200): `{"ok": true, "surface": 1, "node":
{id, kind, name, status, presence, last_seen_at, last_report_at},
"office": {…}, "endpoints": {…}, "heartbeat_s": 60, "report_s": 300}`.
410 `retired` and 401 as for desks; the daemon stops heartbeating and
`maluctl estate status` says why.

**The report**

```json
{"ts": "2026-10-30T09:15:02Z", "boot_id": "…", "uptime_s": 86400,
 "units": [{"unit": "postgresql@18-main.service", "active": "active", "sub": "running", "restarts": 0},
           {"unit": "maludb-mc2dbd.service", "active": "active", "sub": "running", "restarts": 0},
           {"unit": "maluos-vault.service", "active": "active", "sub": "running", "restarts": 0},
           {"unit": "maluos-gateway.service", "active": "active", "sub": "running", "restarts": 1},
           {"unit": "maluos-agent@helpdesk.service", "active": "failed", "sub": "failed", "restarts": 3}],
 "agents": [{"name": "helpdesk", "principal": "agent:helpdesk", "active": "failed", "sub": "failed", "owner": "user:ed", "tasks": true, "sandbox": "strict"}],
 "gateway": {"ok": true, "version": "0.3.3", "backends": [{"name": "local", "kind": "ollama_local", "healthy": true, "loaded": ["qwen3:8b"]}],
             "queue": {"queued": 0, "running": 1}, "expected_wait_s": {"fast": 0, "quality": 4}},
 "vault": {"ok": true, "alerts": [{"id": 9912, "ts": "2026-10-30T08:40:11", "kind": "budget_exhausted", "principal": "agent:helpdesk", "title": "…"}]},
 "updates": {"pending_count": 3, "security_count": 1, "reboot_required": false, "lists_refreshed_at": "…", "last_automatic_run_at": "…"},
 "disk": [{"mount": "/", "size_gb": 95, "used_pct": 41}, {"mount": "/var/lib/postgresql", "size_gb": 800, "used_pct": 63}],
 "memory": {"total_mb": 64000, "available_mb": 21000, "swap_used_mb": 0},
 "load": [0.8, 0.9, 1.1], "cpu_cores": 16}
```

Units are the fixed list the package knows (PostgreSQL, mc2dbd, vault,
gateway, every `maluos-agent@` unit present, `maluos-estate` itself)
read through `systemctl show`; the rest is the shared status module. A
field that cannot be read is `null` with an `errors` list at the top, so
a broken gateway never hides a full disk.

**Nodes answer** (`GET /api/v1/estate/nodes`, `GET /api/v1/desks/estate`)

```json
{"ok": true, "surface": 1, "office": {…}, "fetched_at": "…",
 "nodes": [
   {"id": 57, "kind": "server", "name": "db-1", "hostname": "db-1", "presence": "online", "last_seen_at": "…", "last_report_at": "…",
    "health": "warning", "summary": "1 agent failed · 3 updates pending (1 security)",
    "units": {"up": 4, "down": 1}, "agents": {"count": 1, "running": 0, "failed": 1},
    "gateway": {"ok": true, "backends_healthy": 1, "backends": 1, "queued": 0, "running": 1},
    "updates": {"pending_count": 3, "security_count": 1, "reboot_required": false},
    "disk_max_pct": 63, "memory_available_pct": 33, "load1": 0.8,
    "report": { … the full last report, only in the single-node answer … }},
   {"id": 42, "kind": "desk", "name": "Ed's desk", "owner": {"display_name": "Edward Honour"}, "presence": "online", "last_seen_at": "…",
    "health": "ok", "summary": "online", "facts": {…}}],
 "alerts": [
   {"id": 301, "ts": "…", "node_id": 57, "node": "db-1", "kind": "agent_down", "severity": "warning", "title": "agent helpdesk failed (3 restarts)", "cleared_at": null},
   {"id": 299, "ts": "…", "node_id": 57, "node": "db-1", "kind": "vault_alert", "severity": "warning", "title": "budget exhausted: agent:helpdesk", "cleared_at": null}]}
```

`health` is `ok`, `warning`, `critical` or `offline`, computed by the
kernel from the last report with fixed rules: offline (presence) →
`offline`; a unit of the fixed list down, an agent failed, a vault alert
open, a reboot required, disk over 85 % → `warning`; PostgreSQL or the
vault down, disk over 95 %, memory available under 5 % → `critical`.
`alerts` are the open estate alerts the kernel raised from those rules
plus `node_offline`; an alert clears when the next report no longer
shows its cause, and `cleared_at` is then set (the answer carries open
alerts and those cleared in the last hour). `GET …/nodes/ID` returns one
node with its full report.

## The kernel half (maludb-os-core)

For the owner's approval, as db/187 was:

- db/188: `locations.kind` CHECK gains `server`, `inference`;
  `locations.report jsonb`, `last_report_at`, `public_key text`,
  `enrolled_by_member_id`; `desk_enrollment_codes.kind` (`desk` default;
  `server`, `inference`) and the minting form offers the kind;
  `mcp_access_tokens.scope` gains `node`; `estate_node_reports`
  (location_id, ts, report) kept to 24 rows per node by the sweep;
  `estate_alerts` (location_id, kind, severity, title, raised_at,
  cleared_at, report_ts) with one open row per (node, kind, title).
- `html/api/v1/estate/{join,heartbeat,me,leave,nodes}.php` sharing the
  desks' code; `html/api/v1/desks/estate.php`; the health rules and alert
  raising in the heartbeat handler; the presence sweep raises and clears
  `node_offline` for nodes as for desks.
- `endpoints.estate` on the desks' answers when the owner's role allows
  (the kernel's role to use is the owner's choice; "system manager" or
  "operator" exist today in Agent HR's vocabulary).
- Settings → Desks becomes Settings → Estate: desks and nodes, their
  health, the alerts, the code minting with a kind.
- proof `bin/test_estate_nodes.php`.

## The host half

**maluos-estate** (new, 0.1.0; seeds: server and desktop)

- `lib/maluos_estate/client.py`: the HTTP client, the config and state
  files, `join`, `heartbeat`, `me`, `leave`, `nodes`, moved out of
  `maluctl.d/office.py`, which then imports it (maluos-desk depends on
  maluos-estate).
- `lib/maluos_estate/report.py`: the shared status module (`host`,
  `units`, `agents`, `gateway`, `vault_alerts`, `updates`, `disk`,
  `memory`, `load`), moved out of the session, which imports it; the
  session's reads stay byte-for-byte what they are (the boot test's
  state checks do not change).
- `lib/maluctl.d/estate.py`: the commands above; `join` on a desk
  execs `maluctl office enroll`.
- `bin/maluos-estated`: the heartbeat daemon (presence, facts, the
  report every `report_s`, `offline` on SIGTERM, 401/410 handling, a
  retry ladder on network errors: 10 s, 30 s, 60 s, then `heartbeat_s`).
- `systemd/maluos-estate.service` (User=maluos-estate,
  `ConditionPathExists=/etc/maluos/estate.yaml`, `WantedBy
  multi-user.target`); `join` starts it, `leave` stops it.
- postinst: the `maluos-estate` system user; the `identities` lines in
  vault.yaml and gateway.yaml (an idempotent edit, as the office rung is
  for the gateway catalogue); `systemd-tmpfiles` for
  `/var/lib/maluos/estate`.
- Files: `/etc/maluos/estate.yaml` (0644: surface, url, office, node,
  endpoints, heartbeat_s, report_s, secret names, joined_at; no token),
  `/var/lib/maluos/estate/state.json` (the last heartbeat and report
  outcome, 0644, written by the daemon), the vault entries of decision 3.
- `maluctl estate report` prints what the next report would carry, so an
  operator can see it without the kernel.

**maluos-vault** (0.4.0): principal kind `host`; `maluctl principal add
host:NAME --kind host`; the ledger's `alert.%` rows readable by a `host:`
principal (today: the owner of the alerting principal and operators).

**maluos-gateway** (0.3.4): nothing but the `identities` map honouring
`host:` (it already honours any ref); listed so that the version is
bumped together if the health answer needs `loaded` for the report.

**maluos-desk** (0.4.0): `office.py` on the shared client;
`maluctl office estate [--json] [--refresh]` (cache
`~/.cache/maluos-estate/office.json`, as apps and agents are cached); the **Estate page** in the Desk window (`PAGES` gains
`("estate", "Estate", "network-workgroup-symbolic")` when
`office.estate.available`): a header with the estate's counts (nodes
online/offline, open alerts), one group per node (kind, name, presence,
health with its colour, the summary line, "Last seen 2 min ago"), a
node's expander with units, agents, gateway, updates, disk, memory, and
the alerts group at the top when any is open. Each node row offers
"Open a terminal" (the `ssh` line, through the same terminal spawn as
the Agents app's) and nothing else. The mock office grows the estate
endpoints, two node kinds, `/mock/report` (set a node's report) and
`/mock/alert` (raise one), and answers `endpoints.estate` for every
desk.

**maluos-desktop-session** (0.7.0): the status reads from
`maluos_estate.report`; `office_estate_read()` after an ok heartbeat
when `endpoints.estate` is set (as agents and apps are read), cleared on
leave; `office.estate` in the state: `{available, fetched_at, error,
nodes: [summary rows], alerts: [open], counts: {nodes, online, offline,
alerts}}`; notifications on transitions seen between two reads: a node
went offline ("db-1 is offline", urgency 2), a node came back, an alert
raised ("db-1: agent helpdesk failed", with "Open Estate" as the
action), with the same dedup the grant notifications use; the indicator
line "Estate: 3 nodes · 1 alert" under the Office line when available;
`OfficeAction(estate)` opens the Desk on the page.

**maluos-meta** (0.2.7): `maluos-server` and `maluos-desktop` depend on
maluos-estate.

## Test (tests/qcow2-boot-test.sh, the office section)

The desktop image carries the server profile, so one VM is both the
server node and the desk; the mock office runs as `nobody` on 18080 as
today.

1. `sudo maluctl estate join http://127.0.0.1:18080 --code node-code --name test-node`
   → "joined: server 'test-node' (#57) at Mock Office as host:…";
   `/etc/maluos/estate.yaml` exists without a token;
   `sudo -u maluos-estate maluctl secret list` shows `estate-node-token`
   and `estate-node-key`; `systemctl is-active maluos-estate` is active.
2. A desk code cannot join a node and a node code cannot enrol a desk
   (403 `bad_code` both ways).
3. `maluctl estate report --json` has `units`, `gateway.ok == true`,
   `agents` with `demo` running, `disk[0].mount == "/"`.
4. The mock office's `/mock/nodes` shows the node online with
   `last_report_at` set within `report_s` (the mock answers
   `report_s: 10` for the test).
5. `sudo maluctl office enroll …` as today; `maluctl office estate
   --json` lists two nodes (the server node and the desk) and no alerts;
   `maluos-desktop-session --once` state has `office.estate.counts.nodes
   == 2`.
6. `sudo maluctl agent stop demo`; within 15 s `maluctl office estate
   --json` has an alert `agent_down` for `test-node` and the node's health
   `warning`; the session state has the alert and the session log has the
   notification line "test-node: agent demo …".
7. `sudo maluctl agent start demo`; the alert clears (`cleared_at` set)
   within 15 s.
8. `sudo systemctl stop maluos-estate` → the mock shows the node
   `offline` at once (the clean `offline`); the session notifies
   "test-node is offline"; start it again → online.
9. `sudo maluctl estate leave` → files gone, the two secrets gone, the
   unit stopped and inactive, the mock shows the node retired; the
   existing `office leave` checks unchanged.
10. `maluctl estate join` on a desk-only path: with `estate.yaml` absent
    and `office.yaml` present, `maluctl estate status` says "this desk is
    node #41 of Mock Office (its desk enrolment)".

The server image's test (`tests/qcow2-boot-test.sh` server section) adds
steps 1 to 4 and 9 with the mock office started there too, so a server
without a desk is covered.

## Deferred to slice 2 and later

- Actions on remote nodes from the Estate page (restart an agent, apply
  updates, leave): slice 2, with the envelope and the node key.
- A desk's full report to the system manager: slice 2.
- Node-to-node traffic and the overlay: slices 3 and 6.
- Linking `server` rows to operator-typed `office` rows: kernel, later.
- Alert routing to a person who is not at a desk (mail, the kernel's
  notifications): the kernel's own notification work, outside this slice.

## Effort

| Part | Size | Notes |
|---|---|---|
| maluos-estate (client, report module, daemon, commands, packaging) | M | most of the client and the report already exist as code |
| the refactor of office.py and the session onto the shared modules | S | no behaviour change; the existing boot checks prove it |
| maluos-vault host principals and alert visibility | S | |
| the mock estate | S | |
| the Estate page and `office.estate` in the session | M | |
| the boot tests (desktop and server) | S | |
| the kernel half | M | separate repository, owner's approval first |

About the size of Phase 12 slice 7. Two build-and-test rounds on the
desktop image, one on the server image.
