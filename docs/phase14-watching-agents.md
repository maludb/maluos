# Phase 14 slice 4: the agents that watch the servers

2026-11-13. The design, agreed by the owner the same day (the six recommendations below, all accepted).
Step 4a is written; 4b to 4d are not. Follows `docs/phase14-database-server.md` (gap 7, the owner's answer of
2026-11-12) and `docs/phase14-application-servers.md` ("Watching agents").

## What the owner asked for

The database server is watched in the background by three agents: PostgreSQL, Linux and security. They
run on the kernel server if that can be achieved, and act on the database server through the estate. The
database server itself runs what belongs with the data (PostgreSQL, the engine, the memory listener) and
no agent.

## What exists today

| Piece | State | Where |
|---|---|---|
| The node report | Every estate node sends one with its heartbeat: units, agents, gateway, vault, updates, disk, memory, load, host, overlay, `database` (where the data is). Under 32 KB, no secrets. The kernel keeps the last 24 per node | `maluos-estate` `report.py`; kernel db/188 `estate_node_reports` |
| Node actions | The kernel queues an action for a node; the node runs it if its own allow-list permits (`restart_agent`, `start_agent`, `stop_agent`, `apply_updates`; `reboot` off by default) | `maluos-estate`; kernel `estate_actions` |
| The Sysadmin | A `system_one` agent in the IT department. Runs fixed playbooks: collect, ask typed questions, decide by thresholds, act only through granted tools. Starts in shadow (report only). **It watches the kernel's own host only** (local `systemctl`, local disk, the local journal) | kernel `mcp/agent_runner/system_one/` |
| Approvals | An agent's action pauses for its approver (in IT: the department's manager) | kernel approvals |

## The three gaps

1. **A database server cannot join the estate.** `maluctl estate join` makes a host principal, maps it in
   the vault and the gateway, and stores the node's key and token in the vault. A database server has
   neither. So it sends no report and takes no action.
2. **The report is too thin to watch a database or a server's security.** Nothing in it comes from
   inside PostgreSQL, from the login records or from the listening ports.
3. **No agent reads other nodes' reports.** The Sysadmin's collectors are local.

## The design

### 1. A database server joins as a bare node

A new way to join, for a server with no vault and no gateway:

```
sudo maluctl estate join https://app.example.com --code ABCD-EFGH --kind server --bare
```

- No host principal, no identity mapping, no agents, no inference, no memory federation, no overlay.
- The node token and the node's signing key are kept in root-only files
  (`/var/lib/maluos/estate/node.token`, `node.key`, mode 0600), not in a vault. The node service already
  accepts its token from the environment, so this is a small change.
- The node service does three things only: heartbeat with the report, the collectors below, and node
  actions from its allow-list.
- First boot does it from the plan: `role: database-server` with `enroll: {kind: estate, url, code}`.
  `/office-setup` asks for it when it sets up a database server.
- The kernel marks the node `node_role = database` (the column exists since db/194), so the agents know
  which checks apply.

The trade against "the vault holds every secret": one token and one key in root-only files on a server
that already holds the database's own key and the admin credential the same way.

### 2. Collectors: plain code on every node, not agents

Three new parts of the node report, each read without privilege where possible, each null and named in
`errors` when it cannot be read. Numbers and short facts only: no query text, no log lines with data.

| Part | On | What it carries |
|---|---|---|
| `postgres` | a node that runs a cluster (the database server; a single host) | connections against `max_connections`; the longest transaction and the longest lock wait (seconds, not the query); replication and WAL size; each database's size; the worst tables' dead-tuple share and last autovacuum age; transaction-id age; counts of ERROR/FATAL/PANIC in the server log since the last report; days until the server certificate expires; whether a superuser other than `postgres` exists |
| `linux` | every node | what the report has (disk, memory, load, units, updates) plus: failed units by name, a pending reboot, clock sync, inode use, the oldest and newest backup if the backup directory is configured |
| `security` | every node | failed logins and their sources (counts per address, top ten); successful logins from addresses not seen before; `sudo` uses (count, the users); listening ports against the set expected for the node's role; pending security updates; a digest of `/etc/maluos` and of the units, so a change shows; the firewall's state |

- PostgreSQL is read through a role `maluos_monitor` (member of `pg_monitor`, no other right), by peer
  authentication on the database server. Never a superuser, never the admin role.
- The security part needs the journal and the login records: the node service's user joins
  `systemd-journal` and `adm`. Nothing else is opened.
- A fourth small thing travels with the report: **redacted log excerpts**, at most twenty lines per
  report, only lines at warning level or worse from PostgreSQL, the kernel and sshd, passed through the
  redaction the Sysadmin already uses (`system_one/redact.py`, ported). This is what lets an agent judge
  a log line; it is the only free text that leaves a node. Decision 3 below.

Cadence: the heartbeat's (the report already travels with it). The kernel keeps a longer, thinner
history for trends: one row per node per ten minutes with the numbers only, kept thirty days
(`estate_node_samples`), so "the disk fills in nine days" can be said.

### 3. Three agents on the kernel server

Three `system_one` agents in the IT department, beside the Sysadmin, each with one playbook. They read
the reports and samples the kernel already holds; they never connect to another server.

| Agent | Playbook | Watches | Examples of a finding |
|---|---|---|---|
| **Database administrator** | `watch_postgres` | every node with a `postgres` part | connections above 80 % of the limit; a transaction open for an hour; dead tuples above 20 % with no autovacuum in a day; transaction-id age past half the wraparound limit; the certificate expires in under thirty days; a second superuser appeared |
| **Linux administrator** | `watch_linux` | every `server` node | a disk that will fill within fourteen days at the current rate; a failed unit; a reboot pending for more than seven days; the clock not synchronised; the node silent for three heartbeats |
| **Security officer** | `watch_security` | every `server` node | failed logins above a threshold or from one address in a burst; a login from a new address; a listening port outside the node's expected set; a change to `/etc/maluos` or a unit that no approved action explains; security updates pending for more than three days |

How they decide:

- **Numbers by thresholds**, in the playbook's versioned config. No model is needed for these, and they
  are most of the value.
- **Log lines by typed questions** (harmless / minor / degraded / serious / critical; data at risk;
  someone probing), as the Sysadmin does today. Which model answers is decision 2.
- **Shadow first**, like every `system_one` agent: they record what they would have raised until a
  person switches them to live.
- **Findings advise.** A finding goes to the IT department's manager with the evidence (the numbers, the
  node, the time). Nothing blocks or changes a server on a finding alone.

What they may do, each through the kernel's approvals and each only if the node's own allow-list permits:

| Action | For | New |
|---|---|---|
| `apply_updates`, `reboot` | every server | no |
| `restart_unit` for a named unit from a fixed list per role (`postgresql@18-main`, `maludb-mc2dbd`, `apache2`, the application's units) | every server | yes |
| `postgres_cancel` / `postgres_terminate` a backend by pid, run locally as `maluos_monitor` (granted `pg_signal_backend`) | the database server | yes |
| `postgres_vacuum` a named table | the database server | yes, decision 4 |

An agent never gets a shell, never runs SQL of its own writing, and never holds a credential for another
server. The node runs a fixed verb with checked arguments, as it does today.

The existing Sysadmin keeps the kernel's own host and the applications; its local probes stay. Whether
it is folded into the Linux administrator later is not part of this slice.

### 4. Application servers and the kernel server

The same collectors run on every node, so the Linux administrator and the security officer watch the
kernel server and every application server too, from the first day. An application server has a vault
and joins the ordinary way; nothing else differs.

## What is built, in order

| Step | What | Proof |
|---|---|---|
| 4a | The bare join; `role: database-server` enrols; `node_role` set from the report | boot test: the second cluster's server joins bare, reports, runs `apply_updates` refused/allowed by its list |
| 4b | The three collectors and the samples table | unit tests on fixture data; boot test: each part present, no secret and no query text in a report |
| 4c | The three agents and playbooks in shadow; findings to the IT manager | kernel proof: fixture reports produce exactly the expected findings; nothing sent in shadow |
| 4d | The new node actions with approvals | boot test: a long transaction made, the finding raised, the cancel approved and done; an unlisted unit refused |

4a and 4b are MaluOS with a small kernel change; 4c is kernel; 4d is both. Each step can ship alone.

## The owner's decisions (2026-11-13: every recommendation accepted)

1. **The bare join** (section 1): a database server keeps its node token and key in root-only files
   because it has no vault. Recommended. The alternative is to put a vault on the database server, which
   means a tenant and platform services there, against "only what belongs with the data".
2. **Which model judges log lines.** The Sysadmin's harness asks JEV, TypeSafe's model. Options:
   (a) thresholds and fixed patterns only in this slice, no model, log judgement added later;
   (b) the office's own gateway model answers the same typed questions;
   (c) JEV where an office has it, otherwise (a).
   Recommended: (a) now, because the numeric findings carry most of the value and need nothing an office
   may not have; (b) as a follow-up once it has been calibrated.
3. **Redacted log excerpts leave the node** (section 2). Needed for 2(b) or 2(c); with 2(a) they can be
   left out entirely for now, and only counts travel. Recommended: leave them out with 2(a).
4. **How far the database administrator may act.** Recommended for this slice: cancel and terminate a
   backend, restart PostgreSQL, each approved. Vacuum, configuration changes and anything touching data
   stay a person's.
5. **Three agents or one.** Three, as you described them, each with its own playbook, thresholds and
   findings (recommended: a manager sees who raised what, and each can go live separately). One "IT
   watch" agent with three playbooks is less to hire and budget.
6. **Who receives findings.** The IT department's manager, as approvals already work. On a new office
   that is the administrator. Say if security findings should go somewhere else.

## As built: step 4a (2026-11-13)

- **maluos-estate 0.8.0**: `maluctl estate join URL --code CODE --bare`. No host principal, no identity
  mapping, no overlay, no inference key. The token and the key are `node.token` and `node.key` in
  `/var/lib/maluos/estate` (0700), files of the user `maluos-estate` (0600): the node service runs as that
  user, so "root-only" in the design became "the node service's user and root". `leave` and `status` know
  a bare node. A plain join on a server with no vault says to use `--bare`.
- The node's facts carry `role` (`database-server`, `application-server`, `kernel`) from first boot's
  record. On a database server the report lists the cluster, the listener and the node service only, so
  the idle vault and gateway raise no alert.
- **maluos-firstboot 0.1.20**: `role: database-server` with `enroll: {kind: estate, url, code}` joins bare.
- **Kernel** (branch `phase14/application-servers`): a join or a heartbeat naming a role sets
  `locations.node_role`; the nodes answer carries `role`. Proof: `bin/test_estate_nodes.php` (four new
  checks).
- The default allow-list of a bare node is `apply_updates`; `reboot` is added with
  `maluctl estate actions allow`.
- Tests: `tests/estate-bare-local-test.sh` (13 checks against the mock office); a boot-test section,
  "a bare node", against the real kernel (written; see the commit for whether it has run).
- The database server reaches the kernel at its public URL (`https://app.<domain>`), like any node: it
  needs a route to the proxy. Not built yet: `/office-setup` asking for the enrolment on a database
  server (the plan's `enroll` block does it).

## Not in this slice

- Agents running on an application server (it can host them; these three run on the kernel server).
- Metrics dashboards or graphs: the samples table makes them possible; nothing draws them yet.
- Backups themselves: the Linux part reports their age if configured; making and testing backups is its
  own piece of work.
- Intrusion prevention: the security officer reports; it blocks nothing.
- Slice 5 (a key per application, TLS on the door and the relay).
