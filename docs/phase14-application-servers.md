# Phase 14 slice 3: application servers (design)

Written 2026-11-12. It is the note that docs/phase14-database-server.md
(decision 4, slice 3) says is written before slice 3 starts. The owner
answered its five questions the same day ("The owner's decisions" at the
end); the text below is the design as decided. Nothing here is built.

## The layout this serves

The owner's target (2026-11-12):

```
                 TLS proxy (the owner's)                     the LAN
   example.com, app., os.  ─────────►  kernel server   ◄───────────────┐  the applications' door (8081)
   hr.example.com          ─────────►  application server 1 ───────────┤  and the applications' internal
   projects.example.com    ─────────►  application server 2 ───────────┘  ports, admitted by address
                                       database server
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

### 1. An application server is a MaluOS server without the kernel

`role: application-server` in `firstboot.yaml` (and the installer's role
question). First boot on it:

- provisions the **platform services** as any MaluOS server does: the
  tenant, the vault, the gateway and the memory face, so agents can run
  there. Agents that support applications and act as the IT department
  are a core premise of MaluOS (the owner, 2026-11-12); an application
  server hosts its own (its Linux and security agents, agents for the
  applications it carries) beside the kernel's agents, which stay on the
  kernel server's runner;
- provisions **no** kernel and no MaluDB API of its own (it uses the
  kernel server's through the door);
- joins the estate with the code from the plan (`enroll`), which gives it
  a node token;
- installs the applications the plan names (below).

The image is the server image as it is: `maludb-os-core` and `maluos-apps`
are installed (PHP, Apache, composer, the installer's code) and the kernel
is simply not provisioned, which is already how a server ships.

**Its platform data, and gap 8.** The services' data is in PostgreSQL, and
PostgreSQL is on the database server. Every MaluOS server makes the roles
`maluos-vault`, `maluos-gateway`, `maluos-memory` and the database `maludb`
under fixed names today, so a second server on one database server resets
the first one's passwords. Slice 3 gives each server its own names there:

- the database `maludb_<node>` (copied from the server's template, as the
  kernel server's is), and the roles `maluos-vault-<node>`,
  `maluos-gateway-<node>`, `maluos-memory-<node>`; `<node>` is the
  server's host name, lower case, checked against what exists;
- the kernel server keeps the plain names, so an estate provisioned
  before slice 3 needs no change;
- `service_login()` and the three components take the names from one
  function (`platform_names(cfg)`); the daemons already read `pg_user`
  and the database from their configuration when the data is remote.

Each application server therefore needs the database server's admin
credential at first boot, as the kernel server does (the plan's medium,
`maluctl db export`), and the database server's `clients` must admit it.

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
- The application's roles and database are still made by the kernel's
  side in `prepare`, although the application server holds the admin
  credential too (section 1): one place decides names and ownership, and
  the application's installer never needs more than its own roles.

### 3. The applications' door on the kernel server

A third Apache vhost on the kernel server, bound to its **LAN address**
(port 8081) and admitted **by address**: `Require ip` for the application
servers' addresses, written by first boot from
`components.maludb-os-core.application_servers` (a list of addresses or
networks, the same idea as the database server's `clients`).

| Path | Goes to | For |
|---|---|---|
| `/api/v1/{directory,agents/chat,notify,apps,runs/facts,ledger}` | the internal API, those paths only | everything an application calls, under its application token |
| `/api/v1/estate/apps/{prepare,register}` | the same | the installer's two calls, under the node token |
| `/maludb/` | `127.0.0.1:8000` | the application's episodes and memory |
| `/model/` | `127.0.0.1:8816` | an application's own model credential (K24) |

It is an allow-list, like the public vhost's. The internal vhost on
`127.0.0.1:8080` serves every PHP handler and must not be widened.
`OS_INTERNAL_URL`, `MALUDB_API_URL` and the model URL in a remote
application's environment point at the door, by the kernel server's LAN
name or address.

In the other direction the Actions MCP posts to
`http://<application server>:<APP_INTERNAL_PORT>`: the application's
internal vhost listens on the application server's LAN address and admits
the kernel server's address only. The registry's `base_url` becomes that
address (the code already accepts any URL; only the installer writes
loopback).

**LAN addresses, not the overlay** (the owner, 2026-11-12: it has to stay
understandable to an administrator who knows networks, not MaluOS). What
that means, stated plainly for the handbook:

- The door and the applications' internal ports speak plain HTTP on the
  LAN, as the proxy already does to the office. They are protected by the
  address lists on both sides and by the tokens every call carries.
- The servers belong on a network segment the business trusts (a server
  VLAN), with a host firewall rule beside each listener; first boot writes
  the rule where a firewall is active and says so where none is.
- The addresses must be stable (static or reserved), as the proxy's
  upstreams must be.
- TLS on these two listeners can follow with the per-application keys
  (section 4) without changing the layout.

### 4. Keys: the master key now, a key per application later

Slice 3 ships a remote application with the kernel's `ACTION_TOKEN_KEY`
and `ACTIONS_RELAY_KEY`, exactly as a local one gets them (the owner,
2026-11-12: master key first, tighten later). `prepare` returns them over
the door.

What that means, recorded so it is a decision and not an oversight: an
application server holds a key that can mint a sign-on for any
application of the estate and tokens the kernel's handlers accept. With
plain HTTP on the LAN (section 3) the key also crosses the wire once per
install. The servers and their network segment are therefore one trust
boundary, as one host is today.

The tightening, a later slice, changes no application code:

- a **derived key** per application,
  `HMAC(ACTION_TOKEN_KEY, "application:" + app_key)`, under the same
  variable names; the kernel signs with it whatever is meant for that
  application (the hand-off, claims, the logout notice, the kernel token,
  the run token presented to that application's endpoints, the action
  token and relay, the replay signature) and verifies with it what the
  application sends back;
- `applications.key_mode` (`shared`, `derived`), so running applications
  move one at a time;
- TLS on the door and on the applications' internal ports.

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

Nodes keep the kind `server` (the owner's decision 4). The node's report
carries its role (`kernel`, `application-server`, `database-server`) and
what it runs (the applications and their units; the cluster), and
Settings → Desks shows the role beside the name.

The overlay stays what it is for desks and for servers elsewhere; the
servers of one site do not need it to work together.

### 7. Office setup

`/office-setup` detects the role and runs the interview that fits:

| On | It asks | It does |
|---|---|---|
| a kernel server | as today, plus where the data lives (0.1.3) and, at the end, whether application servers will join: it mints the codes and prints each server's plan fragment | today's phases; the proxy's blocks with an upstream per name |
| an application server | the kernel server's LAN name, the code, the applications, the database server's name and its two files | checks the database server and the door, provisions the platform services, joins, installs, reports |
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
- **Where they run**: the PostgreSQL agent on the kernel server, acting on
  the database server through the estate, as the owner prefers; the
  database server itself runs the node service and its collectors only.
  An application server has its own vault and gateway (section 1), so its
  Linux and security agents may run on it or on the kernel server; the
  collectors are the same either way. The node service must run without a
  vault and a gateway on a database server, which first boot's enrolment
  already assumes; to be proven.

This is its own slice, after application servers work.

## Slices and test

| Slice | Repository | Contents |
|---|---|---|
| 3a | kernel | the door vhost; `/api/v1/estate/apps/prepare` and `register` (the installer's second half as functions); the code naming applications; `app_install.php --kernel`; the registry's `base_url`; `location_id`; the role in the node's report |
| 3b | maluos | `role: application-server` in first boot, the plan and the installer; per-server platform names on the database server (gap 8); the door and its address list rendered by the kernel component; `maluctl app install`, `names --upstreams`; office setup's three interviews; `proxy-config.sh` per name |
| 3c | both | the test below, the handbook's page, the three-machine proof extended to four machines |
| 4 | both | the collectors and the three watching agents |
| 5 | kernel | a key per application; TLS on the door and the internal ports |

**Test.** This VM has no KVM; three VMs under emulation would take most of
a day per run. As slice 1 stood a second cluster in for the database
server, the boot test stands the application server in on the same VM:
the door bound to a second address, an application installed through
`--kernel` with no access to the kernel's credential (run as a user that
cannot read `config/.env`), its handlers bound to that address, then an
agent's action, an approval's replay, a sign-on, a shared read and the
switcher across the door. The real machines are the owner's walkthrough.

**Effort.** 3a is the large part (the installer's second half behind an
API). Each build and boot test is about two hours here. A
realistic estimate is four to six working sessions for 3a to 3c, and two
more for slice 4.

## The owner's decisions (2026-11-12)

1. **Keys**: the master key now, a key per application later (section 4).
2. **LAN addresses** between the application servers and the kernel, not
   the overlay: it has to stay understandable to existing administrators
   (section 3).
3. **An application server has a vault** and the platform services with
   it: agents that support applications and act as the IT department are
   a core premise of MaluOS (section 1; it is what makes gap 8 a part of
   this slice).
4. **Roles as labels** on `server` nodes, no new node kinds (section 6).
5. **A join code names the applications** it may install (section 2).
