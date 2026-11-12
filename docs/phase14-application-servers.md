# Phase 14 slice 3: application servers (design)

Written 2026-11-12, a draft for the owner. It is the note that
docs/phase14-database-server.md (decision 4, slice 3) says is written before
slice 3 starts. Nothing here is built.

## The layout this serves

The owner's target (2026-11-12):

```
                 TLS proxy (the owner's)                     the estate's overlay
   example.com, app., os.  ─────────►  kernel server   ◄───────────────┐
   hr.example.com          ─────────►  application server 1 ───────────┤
   projects.example.com    ─────────►  application server 2 ───────────┤
                                       database server  ───────────────┘
                                            ▲   PostgreSQL over TLS, by LAN name
                                            └── kernel server, application servers
```

- **Database server**: PostgreSQL 18 with the engine and its listener.
  No kernel, no application (slice 1; `role: database-server`).
- **Kernel server**: `os.`, `app.`, the public page, the agent runner, the
  MaluDB API, the vault, the gateway. An application server in the owner's
  words, the one that runs the kernel. It may also carry applications, as
  today.
- **Application servers**: one or more applications each, no kernel.
- **Agents**: every agent runs on the kernel server (the runner is there
  and applications never hold a model key). The database server is watched
  by PostgreSQL, Linux and security agents that run on the kernel server
  and act through the estate (the owner's answer on gap 7; "Watching the
  servers" below).

## What the survey found (maludb-os-core at 020bfd0)

Today's installer, `bin/app_install.php apply`, is one root process on the
kernel's host that does two jobs:

| Its steps | Where they act |
|---|---|
| 1 to 7: the code in `/srv/apps/<key>`, composer, the venv, the application's roles and database, ports, `config/.env`, the Apache vhost, `/etc/hosts`, the systemd units, a loopback probe | the application's host and the application's database |
| 8 to 16: the catalog row, the application, its endpoints, the application token, roles read through `app_roles`, status, shares, the action registry file and a restart of the Actions MCP, skills imported, approval policies, grants, the agents hired, health, a real sign-on | the kernel's database (as `app_rw`, acting as a super-admin) and the kernel's files (`mcp/registries/<key>.json`) |

What ties an application to the kernel's host:

1. **The installer itself**: both halves in one process, with the kernel's
   database credential.
2. **Loopback addresses**:
   - `OS_INTERNAL_URL=http://127.0.0.1:8080`: every call an application
     makes to the kernel (directory, chat, texts, reads, the switcher, run
     facts, the ledger). The internal API listens on loopback only.
   - The action registry's `base_url=http://127.0.0.1:<APP_INTERNAL_PORT>`:
     where the Actions MCP posts an agent's actions, and what an approval's
     replay URL is built from.
   - `MALUDB_API_URL=http://127.0.0.1:8000` and the model proxy for an
     application's own credential, `127.0.0.1:8816`.
3. **The kernel's master keys in the application's environment**:
   `ACTION_TOKEN_KEY` and `ACTIONS_RELAY_KEY`. Every token in the system
   is an HMAC with the first: hand-off tokens, claims, logout notices,
   kernel tokens, run tokens, action tokens. An application verifies with
   it, and could therefore mint any of them, for any application or member.
   On one host that is one trust boundary. On another host it is not.
4. **Files read at install only**: `maludb-os.json`, the skills folders and
   the agents' job descriptions are read from the checkout by the
   installer and by `bin/hire_application_agent.php`. Nothing reads
   `/srv/apps` at run time.

What already works across hosts, unchanged: the sign-on redirect, the
logout notice, `app_roles`, shared reads, the runner attaching the
application's MCP endpoints and the health probe all use
`applications.url` and `application_endpoints.url`, which hold the public
name. No kernel endpoint checks the caller's address; they are local only
because of the vhost they are served on. The estate already has the join
pattern needed: a one-time code minted by an operator, exchanged by a
server for a node token bound to a location (`/api/v1/estate/join`,
scope `node`).

## The design

### 1. An application server is an estate node that runs no platform services

`role: application-server` in `firstboot.yaml` (and the installer's role
question). First boot on it:

- provisions **no** tenant, vault, gateway, memory face, MaluDB API or
  kernel (as `role: database-server` provisions none);
- joins the estate with the code from the plan (`enroll`), which gives it
  a node token and an overlay address;
- installs the applications the plan names (below).

The image is the server image as it is: `maludb-os-core` and `maluos-apps`
are installed (PHP, Apache, composer, the installer's code) and the kernel
is simply not provisioned, which is already how a server ships.

Consequence: **gap 8 disappears for application servers.** They make no
service roles on the database server, so nothing collides. What remains
is "one kernel server per database server", which is the estate's own
shape. Cost: no local agents and no local vault on an application server;
by the owner's rule none are wanted there.

### 2. The installer in two halves, joined by an API under the node token

The owner's choice: registration through the kernel's API, so an
application server never holds the kernel's database credential.

```
application server                                kernel server
──────────────────                                ─────────────
app_install.php apply <repo> --kernel URL
  0. POST /api/v1/estate/apps/prepare  ─────────► checks the node may install <key> (the code named it);
     {key, manifest}                              makes the application's three roles and its database on
                                                  the database server (the kernel holds the admin
                                                  credential; the application server never does);
                                       ◄───────── {database: host, port, name, roles and passwords, TLS;
                                                   door URL; the application's signing key; MaluDB token;
                                                   mail settings; the public URL}
  1 to 7. code, composer, venv, migrations as the
     application's owner role, config/.env, vhost,
     units, the probe (as today, on this host)
  8. POST /api/v1/estate/apps/register ─────────► steps 8 to 16 of today's installer, by the same
     {manifest, endpoints that answered,          functions, as the operator who minted the code:
      the action registry, skills as files,       catalog, application (its location = this node),
      the agents' job descriptions}               endpoints, token, roles, status, shares, registry file
                                                  and the Actions MCP's reload, skills, approvals, grants,
                                                  the hires, health, the sign-on check
                                       ◄───────── {application token, what was done, what failed}
  9. writes OS_APPLICATION_TOKEN, restarts units
```

- Both calls are idempotent, as every installer step is now; a re-run
  reconciles.
- `plan` works the same way with a read-only `prepare`.
- Local installs (the application beside the kernel) keep today's path.
- **The code names the applications.** The operator mints the code for
  "an application server for `hr`" (or several keys). A node may register
  only what its code named. Installing an application is a grant of
  power; the node token alone should not carry it.
- Migrations run on the application server as the application's owner
  role, over TLS, by the database server's LAN name. An application whose
  database needs an untrusted extension still needs a template on the
  database server (difference 4 of slice 1), unchanged.

### 3. The applications' door on the kernel server

A third Apache vhost on the kernel server, bound to its **overlay
address** (port 8081), admitted by address to the estate's members:

| Path | Goes to | For |
|---|---|---|
| `/api/v1/{directory,agents/chat,notify,apps,runs/facts,ledger}` | the internal API, those paths only | everything an application calls, under its application token |
| `/maludb/` | `127.0.0.1:8000` | the application's episodes and memory |
| `/model/` | `127.0.0.1:8816` | an application's own model credential (K24) |

It is an allow-list, like the public vhost's. The internal vhost on
`127.0.0.1:8080` serves every PHP handler and must not be widened.
`OS_INTERNAL_URL`, `MALUDB_API_URL` and the model URL in a remote
application's environment point at the door.

In the other direction the Actions MCP posts to
`http://<node>.internal:<APP_INTERNAL_PORT>`: the application's internal
vhost listens on the application server's overlay address and admits the
kernel server's. The registry's `base_url` becomes that address (the code
already accepts any URL; only the installer writes loopback).

Why the overlay and not the LAN with TLS: the internal handlers have no
TLS today and are protected by being unreachable. The overlay keeps them
unreachable from the LAN, authenticates both ends, and needs no
certificates. An application server can depend on the overlay; only the
kernel's own database connection cannot (slice 1, difference 1).

### 4. A key per application

A remote application gets a **derived key**,
`HMAC(ACTION_TOKEN_KEY, "application:" + app_key)`, under the same
variable names. The kernel signs with the application's key whatever is
meant for that application: the hand-off, claims, the logout notice, the
kernel token for `app_roles` and shared reads, the run token the runner
presents to that application's MCP endpoints, the action token and relay
on posts to its handlers, the replay signature. It verifies with the same
key what that application sends back (run facts).

- The application's code does not change: it verifies with the key in its
  environment as before.
- A compromised application server can then forge tokens only for its own
  application.
- `applications.key_mode` (`shared`, `derived`): remote applications are
  `derived` from the start; local ones stay `shared` until re-installed,
  so nothing running breaks. The specs' statement that "an application
  never holds the relay key" becomes true for remote applications.

### 5. Names and the proxy

- The public name of a remote application points at its server. The
  kernel records where an application runs (`applications.location_id` =
  the node), and `maluctl app names --upstreams` prints name, node and
  address.
- `proxy-config.sh` takes the upstream per name from that list instead of
  one `--upstream`.
- The kernel server reaches a remote application's public name through
  the proxy, as it already does for its own names under https
  (`proxy_address`, the marked `/etc/hosts` block); the remote names join
  that block. URLs are registered as `https://`, because `app_roles` does
  not follow a proxy's redirect.

### 6. The estate

Nodes keep the kind `server`. The node's report carries its role
(`kernel`, `application-server`, `database-server`) and what it runs (the
applications and their units; the cluster), and Settings → Desks shows
the role beside the name. New node kinds would touch about ten places in
the kernel for a label; they can follow if a rule ever needs them.

### 7. Office setup

`/office-setup` detects the role and runs the interview that fits:

| On | It asks | It does |
|---|---|---|
| a kernel server | as today, plus where the data lives (0.1.3) and, at the end, whether application servers will join: it mints the codes and prints each server's plan fragment | today's phases; the proxy's blocks with an upstream per name |
| an application server | the kernel's URL, the code, the applications, the database server's name and certificate | joins, checks the door and the database server, installs, reports |
| a database server | the clients and the names | `maluctl provision`, `maluctl db export`, the fragment for the others |

The order an operator follows: database server, kernel server,
application servers. The handbook gets that as its own page.

## Watching the servers (the owner's answer on gap 7)

Three background agents on the kernel server: **PostgreSQL**, **Linux**
and **security**. They follow the kernel's Sysadmin agent's pattern:
read-only, report first, findings advise.

- **What they read**: each node's report, extended by collectors that are
  plain code in the node service, not agents:
  - PostgreSQL (database server): connections against the limit, long
    transactions and locks, replication and WAL, database sizes, dead
    tuples and vacuum age, errors in the server log, certificate expiry.
    Read through a monitoring role (`pg_monitor`), never a superuser.
  - Linux (every node): disk, memory, load, failed units, pending
    updates, a pending reboot, clock sync.
  - Security (every node): failed and unusual logins, sudo use, listening
    ports against the expected set, pending security updates, changes to
    `/etc/maluos` and to the units, the firewall's state.
- **What they may do**: the estate's node actions (restart a unit, apply
  updates, reboot), each through the kernel's approvals.
- **Where it runs**: nothing but the node service on the database server
  and the application servers. This needs the node service to run without
  a vault and a gateway on those roles, which first boot's enrolment
  already assumes for a database server; to be proven.

This is its own slice, after application servers work.

## Slices and test

| Slice | Repository | Contents |
|---|---|---|
| 3a | kernel | the door vhost; `/api/v1/estate/apps/prepare` and `register` (the installer's second half as functions); the code naming applications; derived keys; `app_install.php --kernel`; the registry's `base_url`; `location_id` |
| 3b | maluos | `role: application-server` in first boot, the plan and the installer; the door rendered by the kernel component; `maluctl app install`, `names --upstreams`; office setup's three interviews; `proxy-config.sh` per name |
| 3c | both | the test below, the handbook's page, the three-machine proof extended to four machines |
| 4 | both | the collectors and the three watching agents |

**Test.** This VM has no KVM; three VMs under emulation would take most of
a day per run. As slice 1 stood a second cluster in for the database
server, the boot test stands the application server in on the same VM:
the door bound to a second address, an application installed through
`--kernel` with no access to the kernel's credential (run as a user that
cannot read `config/.env`), its handlers bound to that address, then an
agent's action, an approval's replay, a sign-on, a shared read and the
switcher across the door. The real machines are the owner's walkthrough.

**Effort.** 3a is the large part (the installer's second half behind an
API, and the keys). Each build and boot test is about two hours here. A
realistic estimate is four to six working sessions for 3a to 3c, and two
more for slice 4.

## For the owner to decide

1. **A key per application now** (section 4), or ship remote applications
   with the kernel's master keys first and tighten later? Recommended: now.
   It is the difference between a breach of one application server and a
   breach of the estate.
2. **The overlay between application servers and the kernel** (section
   3), or LAN addresses? Recommended: the overlay. It needs the hub's UDP
   port open between the servers, as the three-machine proof does.
3. **Application servers run no vault, gateway or memory face** (section
   1), so no agent can ever run on one. Recommended: yes.
4. **Roles shown as labels on `server` nodes** (section 6) instead of new
   node kinds. Recommended: yes.
5. **A join code names the applications it may install** (section 2).
   Recommended: yes.
