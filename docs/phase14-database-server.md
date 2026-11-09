# Phase 14: the database server (PostgreSQL on its own MaluOS server)

Planned 2026-11-09 from the owner's observation on the supported
topologies: an office's applications each have their own name prefix, so
they can be served from different application servers, yet first boot,
the daemons and the kernel's installer all assume that PostgreSQL runs on
the host they run on. This document records what the survey of the three
repositories found, decides how the database moves to a server of its own,
and cuts the work into slices. Nothing here is built. The owner decided
2026-11-09 that the database server is a MaluOS server first (decision 1),
a PostgreSQL the operator provides being deferred, and answered the four
planning questions the same day ("The owner's decisions"): the overlay
address, the credential on the medium, `maludb_admin` only, after D7.

## What the survey found

The local database is not one assumption but a set of them, each in a
different place:

| Where | What assumes a local PostgreSQL |
|---|---|
| maluos-firstboot, `maluos_provision.py` | every SQL statement of first boot runs as `runuser -u postgres -- psql` over the Unix socket as the local superuser (`psql()`, `exists()`, `wait_for_postgres()` with `pg_isready`); the MaluDB database, the tenant role and schema, the admin principal, the operators' superuser logins, the listener's role |
| the components of maluos-vault, maluos-gateway, maluos-memory, maludb-api, maludb-os-core | reuse those helpers to create their roles and databases; the kernel component also applies the kernel's migrations with `runuser -u postgres psql -f` |
| the daemons (vault, gateway, memory face) | connect with `pg_host` = the local socket directory and no password: PostgreSQL maps the Unix user to the role (peer authentication); the vault holds every other credential but reaches its own store this way |
| the operators | phase 4 gives every human account a peer-authenticated superuser login with the tenant schema on its search path |
| the kernel component | writes `DB_HOST 127.0.0.1` into the kernel's `config/.env` and `RUNNER_DB_HOST 127.0.0.1` into `runner.env`; mints the MaluDB API token against `localhost:8000`, whose `MALUDB_PG_HOST=localhost` |
| the kernel's application installer (`bin/app_install.php`) | creates an application's roles and database as the local `postgres` user and writes `DB_HOST 127.0.0.1` into the application's `.env`; registers the application in the kernel's database through the kernel's own PDO connection |
| the engine | the MC2DB listener (maludb-mc2dbd) connects over the socket with `PG_CONNINFO host=/var/run/postgresql`; the maludb_core extension lives in the cluster |
| the image | `seeds/server.seed` installs postgresql-18 and the extension on every server; there is no image role that says "database server" or "application server" |

The plugin's topologies A, B and C (docs/office-setup.md) are about where
TLS ends, not where the database is; they stay as they are.

## What the phase delivers

An office whose PostgreSQL runs on another MaluOS server, and later
applications on servers of their own, all from first boot:

```
# the database server: a MaluOS server with the engine and nothing else
firstboot.yaml: role: database-server; database_server: {listen: 0.0.0.0, clients: [192.168.100.0/24], tls: self-signed}

# the office: the kernel, the vault, the gateway, the memory face, with its data elsewhere
firstboot.yaml: database_server: {host: db-1.example.com, port: 5432, admin: maluos_admin, credential: file:/run/media/plans/db-admin.txt, sslmode: verify-full}

# later, an application server: one application, the kernel's installer pointed at the office's database
firstboot.yaml: role: application-server; office: {url: https://app.example.com, database_server: {...}}; apps: {install: [doccloud]}
```

The default, with no `database_server` block, stays exactly today's single
host.

## What exists to build on

| Piece | Reused as |
|---|---|
| `maluos_provision.py`: `psql()`, `exists()`, `qi()`, `ql()`, `wait_for_postgres()`, `set_env()`; the `ctx` every component receives | the one place the connection changes; the components keep calling the same functions |
| the vault: secrets with kinds, grants, `store_secret` from first boot (`pg-<tenant>-password` already exists for the MaluDB API) | the services' database passwords, minted at first boot, granted use-only to each service's user |
| each daemon's yaml (`pg_host`, `pg_user`, `pg_role`, written by its component) | gains `pg_password_ref` (a vault reference) or a certificate pair; the connect functions already take `host` and `user` |
| the kernel component's `write_env()` and the kernel's `.env` keys (`DB_HOST`, `DB_PORT`, `MALUDB_API_URL`) | take the host from the block instead of the literal |
| the kernel's `bin/app_install.php` (`--proxy-address` added for D1c) | `--db-host`, `--db-port`, `--db-admin` with a credential file; the same shape as D1c's kernel change |
| the estate: a server node with a kind, its report, the overlay (`NAME.internal`), the node API | the database server is a node of kind `database`; its report carries the cluster's state; the application servers reach it by its overlay name or a LAN name |
| the installer's plan and First boot screen (`firstboot.components.maludb-os-core`, the Business OS group) | a "Database" group: this server, or a host |
| the first-boot `listener` block (host, port, token) and the operators' peer logins | the listener moves with the database; operators keep peer logins on the database server and get password logins from the office |
| maludb-core's `maludb-core-26` branches (the owner's) and the extension's packaging | the database server's image role is where the engine's packages go |

## Decisions

1. **The database server is a MaluOS server.** First boot prepares it (the
   cluster, the extension, the listener, `listen_addresses`, `pg_hba`,
   TLS, an admin role for the office), the estate sees it (a node of kind
   `database`), and its report tells the operator what the cluster is
   doing. A PostgreSQL the operator provides (a managed service, another
   distribution) is deferred: it needs a hand-made admin role, no listener
   and no extension packaging we control, and it is the request of a
   customer with a database team, who will say what they need.
2. **One connection abstraction, in maluos_provision.py.** `psql()`,
   `exists()` and the migration runner take their connection from
   `cfg["database_server"]`: absent or `local`, exactly today's `runuser -u
   postgres` over the socket; a host, `psql "host=… port=… user=<admin>
   dbname=… sslmode=verify-full"` with the admin credential in `PGPASSFILE`
   (a root-only file written from the plan or the vault, never on a command
   line). Every component keeps calling the same functions, so nothing in
   the components changes but the hard-coded hosts.
3. **Services authenticate with passwords from the vault when the database
   is remote; peer stays for local.** Each component mints a password for
   its role at first boot, stores it in the vault in the service's own
   compartment (`pg-<role>-password`, as the MaluDB API's is today) and
   writes `pg_password_ref` into the service's yaml; the connect functions
   fetch it at start. The vault is the exception: it cannot ask itself, so
   its credential is a root-only file under `/var/lib/maluos/secrets`
   (mode 600, read at start) or a client certificate when the database
   server issues them (decision 5). The kernel's roles (`app_rw` and the
   three MCP roles) already use passwords; only `DB_HOST` changes.
4. **The office's host is the application server by default; the
   application server is a later slice.** Slice 1 keeps the kernel and
   every application on the office and moves only the data. An
   application on its own host (slice 3) needs the kernel's installer there
   with the kernel's database reachable and the kernel's web units off,
   and a registration path that does not require the application host to
   hold the kernel's `app_rw` credential: either the installer registers
   through the office's API with an operator token, or the office's
   installer is run from the office with `--target HOST` and installs the
   application over the overlay. That is the kernel-side design question
   of this phase, left open until slice 1 and 2 hold.
5. **Transport is TLS to the database server, admitted by address.** The
   database server listens on its LAN or overlay address, `pg_hba`
   admits the office's and the application servers' addresses with
   `scram-sha-256` (certificates in slice 2 for the vault and the engine's
   listener), and TLS is on with a certificate first boot makes
   (self-signed, its fingerprint published in the node's report and in the
   plan's `database_server.ca`), or the operator's. The office reaches it
   over the estate's overlay by its stable name (`db-1.internal`), and a
   database server that is also the overlay hub is the recommended layout
   (the owner's decision 1 below); a LAN address stays possible for a
   database server that is not a member yet.
6. **The listener and the operators move with the data.** The MC2DB
   listener runs on the database server (it is the engine's own face); the
   office's `endpoints.memory` point at it. Operators keep peer superuser
   logins on the database server; on the office they get a password login
   as `maludb_admin`, the tenant's owner, minted by first boot into the
   vault, so `psql` on the office still works (`maluctl db psql`) without
   a superuser anywhere but on the database server (the owner's decision
   3 below).
7. **The image roles are seeds, not new images.** `seeds/server.seed` is
   split: `maluos-server` (the base, the vault, the gateway, the client
   tools) and `maluos-database-server` (postgresql-18, the extension,
   mc2dbd); `maluos-business-os` depends on the client only. The server
   ISO carries both; the installer's role question chooses. One image
   still installs everything when no role is chosen (today's behaviour).
8. **Backups and failover are not this phase.** Where the data lives is
   this phase; copies of it are the Professional `backup` service of
   docs/phase9-editions.md, and a standby is Enterprise `fleet`.

## The contract: firstboot.yaml

```yaml
# on the database server
role: database-server
database_server:
  listen: 0.0.0.0            # or the overlay address
  clients: [192.168.100.0/24, 100.100.0.0/16]
  tls: self-signed           # or {cert: PATH, key: PATH, ca: PATH}
  admin: maluos_admin        # the role the office provisions with; its password is minted here and shown once (or taken from the plan)

# on the office (and later an application server)
database_server:
  host: db-1.internal        # or a LAN name or address
  port: 5432
  admin: maluos_admin
  credential: file:/run/media/plans/db-admin.txt    # or vault:… after enrolment
  sslmode: verify-full
  ca: file:/run/media/plans/db-1-ca.pem             # the fingerprint or the certificate first boot published
```

The first-boot summary (`/var/lib/maluos/firstboot/done`) records
`database_server: {host, port, tls, admin}`; `maluctl status` prints where
the data is; the node's report carries it, so the Estate page shows an
office with its database elsewhere and the database server with its
clients.

## Slices

### Slice 1: the office with its database on a MaluOS database server

- maluos_provision.py: the connection abstraction (decision 2), the
  `database_server` block, `PGPASSFILE`, the remote `wait_for_postgres`;
  `maluctl db psql|status` for the operator.
- The components: the vault, gateway, memory and MaluDB API roles with
  passwords from the vault when remote (decision 3); the kernel component's
  `DB_HOST`, `RUNNER_DB_HOST`, the migrations through the connection, the
  API URL unchanged (the MaluDB API stays on the office, its own `PG_HOST`
  from the block).
- The database server's first boot: `role: database-server` prepares the
  cluster, the admin role, `listen_addresses`, `pg_hba`, TLS; the listener
  there; a node of kind `database` in the estate (kernel: the kind in
  db/188's CHECK, additive).
- The kernel's installer: `--db-host/--db-port/--db-admin` (kernel
  repository), applications' databases on the database server, their
  `DB_HOST` from it.
- The installer's plan and First boot screen: the Database group.
- Test: tests/qcow2-boot-test.sh with a second PostgreSQL cluster on the
  same VM standing in for the database server (port 5433, TLS,
  `pg_hba` by address), the office provisioned against it; the local test
  for the provisioning helper against a scratch cluster; the three-machine
  proof gains a fourth machine as the owner's real run.

### Slice 2: the database server as an image role

- `seeds/server.seed` split (decision 7), the metapackages, the ISO
  catalogue, the installer's role question, the boot test with two VMs
  (the database server first, the office joined to it).
- Certificates for the vault and the listener; the fingerprint in the
  node's report.

### Slice 3: application servers

- The kernel-side design of decision 4, written as its own note first;
  then `role: application-server`, one application per host or several,
  the proxy's blocks per host (`proxy-config.sh` learns an upstream per
  name), the estate's node kind `application`.

## Test

The acceptance of the phase is the owner's four machines: a database
server, an office, a GPU node, a desk; the office's `maluctl status` says
its data is on `db-1.internal`; `psql` on the database server shows the
kernel's and the applications' databases; the office's agents, the desks'
enrolment and the estate run as they do today; a reboot of the office
alone keeps every record. Slice 1's boot test proves the same on one VM
with two clusters.

## Deferred

- A PostgreSQL the operator provides (decision 1): with the first customer
  who asks; the connection abstraction is where it plugs in.
- Backups, a standby, failover (decision 8): Professional and Enterprise.
- The application server (slice 3) until the kernel-side design is written.
- Connection pooling (pgbouncer) between application servers and the
  database: when a measured need appears.

## Effort

| Part | Size |
|---|---|
| the connection abstraction and the components (slice 1, host half) | M |
| the database server's first boot and the node kind | M |
| the kernel's installer options (kernel repository) | S |
| the installer's plan and screen, the tests | M |
| slice 2 (seeds, roles, two-VM test, certificates) | M |
| slice 3 (application servers), after its design note | L |

## The owner's decisions (2026-11-09)

The four questions the first draft left open were answered the same day:

1. **The overlay address.** The office reaches its database server as
   `db-1.internal` over the estate's overlay; the database server is the
   estate's hub where the layout allows (it is the one server every other
   member must reach anyway). The LAN address stays possible in the
   contract for a database server that is not a member yet, but the
   runbook recommends the overlay, and `pg_hba` admits the overlay range
   first. Consequence for slice 1: the database server joins the estate
   before the office is provisioned against it, so its name resolves; the
   first-boot order on the office is enrol, then provision the kernel,
   which `maluctl provision` already allows (the enrolment is a component).
2. **The credential on the medium.** The admin credential reaches the
   office as a file on the plan's medium (`credential: file:…`), as the
   contract above shows; no kernel change, and the same path the
   installer already uses for a plan's secrets (`enroll.code`, the
   passphrase). It is read once at first boot and stored root-only under
   `/var/lib/maluos/secrets`; the medium can be removed afterwards.
3. **`maludb_admin` only.** Once the database is remote, operators do not
   get superuser logins. On the office they get a password login as
   `maludb_admin`, the tenant's owner, minted into the vault at first boot
   (`maluctl db psql` uses it); the database server keeps peer logins for
   its own operators as phase 4 made them. The `operators` key of
   firstboot.yaml therefore means "tenant owner" on an office with a remote
   database and "superuser" on a host that runs its own cluster; the
   summary says which. Decision 6 is amended accordingly.
4. **After D7.** The phase starts after the three-machine proof has run on
   the owner's machines (docs/phase13-three-machine-proof.md), so the
   database server is specified against the estate as it really looks,
   and after E7 phase 2 where that is already in flight. Roadmap row E9.

## Open questions

None at planning time. The kernel-side design of application servers
(decision 4, slice 3) is written as its own note before slice 3 starts.
