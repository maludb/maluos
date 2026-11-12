# Phase 14: the database server (PostgreSQL on its own MaluOS server)

Planned 2026-11-09 from the owner's observation on the supported
topologies: an office's applications each have their own name prefix, so
they can be served from different application servers, yet first boot,
the daemons and the kernel's installer all assume that PostgreSQL runs on
the host they run on. This document records what the survey of the three
repositories found, decides how the database moves to a server of its own,
and cuts the work into slices. Slice 1 is built ("Slice 1 as built"); the
rest is not. The owner decided
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

## Slice 1 as built (2026-11-09)

Started on the owner's word while the three-machine proof runs (the
"after D7" of decision 4 was the owner's to waive). What the code does,
where it differs from the plan above, and what it found.

### The admin role, concretely (the owner's decision 3)

The engine already has a delegated administrator, the role `maludb_admin`
("trusted admin delegation": it may run `grant_memory_access`, which hands
out `maludb_user`, `maludb_read` and `maludb_admin`). The database server's
first boot makes the office's role on top of it:

| What | Why |
|---|---|
| `maluos_admin` LOGIN CREATEROLE CREATEDB, `createrole_self_grant = 'set, inherit'` | the tenant's, the services' and the kernel's roles and databases; it may act as the roles it creates (the tenant's schema, an application's database owned by its role) |
| BYPASSRLS | only a role that has the attribute may give it, and the gateway's role needs it (the engine's queue holds every account's requests); the one attribute beyond the two above |
| member of `maludb_admin`, `maludb_user`, `maludb_read` WITH ADMIN OPTION | `GRANT maludb_user TO <tenant>` |
| owner of the MaluDB database (`ALTER DATABASE … OWNER`) | the tenant's schema, the database's `search_path` |
| every privilege on the engine's schemas, tables, sequences and functions WITH GRANT OPTION, and default privileges for what the engine's owner creates later | a service's `SELECT` on the principals, the tenant facades that `enable_memory_schema` creates as the engine's owner |
| `maludb_template`, a template database with `vector` and `maludb_core` and the same delegation | `CREATE EXTENSION maludb_core` needs a superuser; the admin copies the template instead (the kernel's memory database) |
| never SUPERUSER | the owner's decision 3; the boot test asserts that no role but `postgres` is one |

Proved on a scratch cluster (tests/dbserver-local-test.sh): the tenant, the
principals, the vault's, the gateway's and the memory face's schemas, a
second engine database, the kernel's 173 migrations and an application's
database all provision as this role over TLS 1.3 with the certificate
verified.

### What was built

- **maluos-firstboot 0.1.17.** `maluos_provision.py`: `database_target()`
  (none: the local cluster as before; a host: the database server),
  `psql()`, `psql_file()`, `exists()`, `wait_for_postgres()` through it;
  `prepare_remote()` takes the credential and the certificate from the
  medium once (`/var/lib/maluos/secrets/db-admin.password` and `.pgpass`,
  root only; `/etc/maluos/database-server-ca.pem`); `ensure_maludb_database()`
  (created locally, copied from the template remotely); `service_login()`;
  `provision_database_server()` and `ensure_database_server()` for `role:
  database-server` (the table above, the certificate, `conf.d/
  maluos-database-server.conf`, the marked `pg_hba.conf` block, a restart
  only on a change). `maluctl db status | psql | export`; `maluctl status`
  says where the data is. Operators get no database role on an office whose
  data is remote.
- **maluos-vault 0.4.3, maluos-gateway 0.6.2, maluos-memory 0.2.2.** The
  daemons read `pg_port`, `pg_sslmode`, `pg_sslrootcert` and a password: the
  vault from a file of its own (`/var/lib/maluos-vault/pg.password`; a unit
  drop-in opens IP sockets to it, only then), the gateway and the memory
  face from the vault (`system/pg-<role>-password`, a grant to the
  service's own principal: use for the gateway, a broker; read for the
  memory face, since the vault gives mode=use to brokers only). The schemas go through first boot's connection.
- **maludb-api 0.4.1maluos6, maludb-os-core 2026.11.09maluos1.** The API's
  `MALUDB_PG_HOST`/`PORT` with libpq's `PGSSLMODE`/`PGSSLROOTCERT`; the
  kernel's `DB_HOST`, `DB_PORT`, `DB_SSLMODE`, `DB_SSLROOTCERT`, the
  runner's, and `DB_ADMIN_USER`/`DB_ADMIN_PASSFILE` for its installer.
- **The kernel** (branch `phase14/database-server`, a pull request for the
  owner): `app/db.php` and the asyncpg clients (`mcp/pg_tls.py`, the runner)
  read the TLS keys; `bin/app_install.php` takes `--db-host`, `--db-port`,
  `--db-admin`, `--db-passfile`, `--db-sslmode`, `--db-ca`, or the kernel's
  `config/.env`, makes the application's roles and database on the server
  and writes it into the application's `DB_HOST`.
- **maluos-installer 0.3.7.** `firstboot.role` and
  `firstboot.database_server` in the plan (the credential and the
  certificate as `file:` references read at install time; the password
  written root-only into the target, never into `firstboot.yaml`), and the
  Database group on the First boot screen.
- **maluos-estate 0.7.1.** The node's report carries a `database` part.

### Where it differs from the plan

1. **The first provisioning cannot use the overlay name** (the owner's
   decision 1). The overlay is the office's: its members and their keys are
   rows of the kernel's database, and that database is the one on the
   server. An office that reaches its database only over the overlay cannot
   boot the kernel that defines the overlay. So `database_server.host` is
   a LAN name or address at first boot, verified by TLS (the server's
   certificate carries its host name, `<host>.internal`, and what
   `names`/`addresses` add); `clients` then lists the office's LAN network.
   The default of `clients` stays the overlay range for the later members
   (application servers, slice 3). Moving the office itself onto the overlay
   afterwards needs the overlay to come up from the office's local state
   before the kernel starts, on every boot; that is not tested and is a
   question for the owner (below).
2. **No node kind `database` yet.** The kernel knows the kinds in about ten
   places (the CHECK, `NODE_KINDS`, the queries of inference, memory and
   delegation, the web console). The database server enrols as a `server`
   node and says what it is in its report's `database` part; the kind
   moves to slice 2 with the image role.
3. **The kernel's own TLS verification waits for the kernel's pull
   request.** Until it is merged and re-vendored from main, this tree
   carries the branch; the kernel then verifies the certificate
   (`DB_SSLMODE=verify-full`). The MaluDB API and the three daemons verify
   it already.
4. **An application's own provisioning script** (`database.provision`) that
   calls `runuser -u postgres psql` does not reach a database server; the
   installer hands it libpq's variables (`PGHOST`, `PGUSER`, `PGPASSFILE`,
   …), so a plain `psql` in it works. An application whose own database
   needs an untrusted extension (the engine, `vector`) needs a template on
   the server; none of the four default applications does.
5. **Moving an existing office's data** to a database server is not in
   this slice: the block is for an office provisioned against the server
   from its first boot (the kernel's migration ledger and markers are local
   state of the office).
6. **Engine upgrades** (`ALTER EXTENSION maludb_core UPDATE` in each
   database and in the template) are the database server's work and have
   no command yet (`maluctl db upgrade`, slice 2).

### The operator's steps

```
# the database server (a MaluOS server; firstboot.yaml or the plan)
role: database-server
database_server: {listen: 0.0.0.0, clients: [192.168.100.0/24], names: [db-1.example.com]}
sudo maluctl db export /media/plans        # db-admin.txt, db-ca.pem, database-server.yaml (and the listener's token)

# the office (the plan, or the First boot screen's Database group)
firstboot:
  database_server: {host: db-1.example.com, credential: 'file:LABEL=PLANS:/db-admin.txt', ca: 'file:LABEL=PLANS:/db-ca.pem'}
sudo maluctl db status                      # where the data is, reached as maluos_admin, not a superuser
sudo maluctl db psql                        # a session there, as the admin role
```

### Test

- `python3 tests/database-server-test.py`: 16 tests (the target, the
  credential, the pg_hba block, the plan, what the installer writes).
- `tests/dbserver-local-test.sh`: a scratch cluster on this host made a
  database server by the real first-boot code, an office provisioned
  against it, the services' logins, the installer's database steps.
- `tests/qcow2-boot-test.sh` (server image): after every other check, a
  second cluster of the VM is made a database server, the office is
  provisioned against it with `maluctl provision --force`, and the VM's own
  cluster is stopped: the vault, the gateway, the memory face, the MaluDB
  API and the kernel must still answer. `BOOT_TEST_DBSERVER=0` skips it.

### Status

Built. The unit tests and the scratch-cluster test pass, and the server
image's UEFI boot test passed on 2026-11-10 (234 checks, none failed; its
last section is this slice's proof). The kernel's pull request is recorded
here when it is opened.

What the boot test found on the way, each fixed before the passing run:

- The memory face asked the vault for its database password with
  `mode=use`, which the vault gives to brokers only. It now reads the value
  under a read grant (`service_login(..., level="read")`); the gateway, a
  broker, keeps its use grant.
- The MaluDB API's and the kernel's health waits counted tries, and a
  refused connection returns at once: one minute and ninety seconds. They
  now wait by the clock (240 s and 300 s).
- The kernel's health wait failed in two runs of four even at 300 s, with
  three seconds allowed per request. With twenty seconds per request it
  passed. The cause is not confirmed: the health route writes one activity
  row, and under emulation with every service restarting the request may
  simply be slow. One passing run does not settle it; the component's
  error now carries the last failure, and the test prints the Apache log
  and the server's log if it happens again.
- Three checks of the test itself were wrong (the operator's name was the
  tenant's, an instant of pg_stat_activity instead of the server's
  connection log, a health route that never touches the database).

## The split topology: what holds and what does not (2026-11-12)

The owner's target layout, stated 2026-11-12 after the first walkthrough: one
database server; one application server running the kernel (`os.`, `app.`,
the public page); further application servers each running one or more
applications and no kernel; on the database server no agents but database
and Linux support agents, if any. The walkthrough waits for application
servers.

| # | Gap | State |
|---|---|---|
| 1 | An application on a server of its own. The kernel's installer clones into `/srv/apps` of the kernel's host, registers `http://127.0.0.1:<port>`, writes `OS_INTERNAL_URL=http://127.0.0.1:8080` (the internal API listens on loopback only), enables units and a vhost locally | open: slice 3, design below |
| 2 | Office setup did not know the database server | **closed** in maluos-office-setup 0.1.3: Phase 1b of the interview, `database-server.py --show/--check/--apply`, the data in `preflight.py` and `verify.sh`, `references/database-server.md` |
| 3 | An office that already holds data cannot be moved | open (difference 5); `--apply` refuses a provisioned kernel without `--data-not-moved` |
| 4 | `proxy-config.sh` renders one upstream for every name | open: with slice 3 |
| 5 | No `application-server` role in the installer, no node kinds `database` and `application` | open: slices 2 and 3 |
| 6 | The overlay name in `maluctl db export` | **closed** in maluos-firstboot 0.1.18: the export names the server by `database_server.names[0]` or its full name; open question 1 answered by the owner 2026-11-12 (the LAN name, for good); the plugin's check explains a name the certificate does not carry |
| 7 | Agents on the database server | open, a design gap: `role: database-server` provisions the cluster and nothing else (no tenant, vault, gateway or memory face), and `maluos-agent@` needs all three, so no agent can run there today. No database or Linux support agent ships either: the kernel's Sysadmin agent watches its own host. What the office has is the server's node report (its `database` part) and the estate's node actions |
| 8 | Two servers on one database server. Every MaluOS server's first boot makes the roles `maluos-vault`, `maluos-gateway`, `maluos-memory` and the database `maludb` under fixed names; against a database server `service_login()` sets each role's password, so a second server resets the first one's | open: must be settled by slice 3 (found 2026-11-12; one database server serves one kernel server until then) |

### Slice 3, the owner's choices (2026-11-12)

- **Registration through the kernel's API.** The installer runs on the
  application server and registers the application with the kernel using an
  operator token; the application server never holds the kernel's `app_rw`
  credential. (The alternative, the kernel's host installing onto the other
  host, was declined: it needs root from the kernel's host on every
  application server.)
- **The layout** above.

The design note is docs/phase14-application-servers.md (2026-11-12, a draft
for the owner).

### Slice 3, what the design note has to settle

1. The kernel's side: an API for what `app_install.php` does through
   `app_rw` today (the application row, its endpoints, roles, registry,
   token, the agents' hires), under an operator token; `base_url` and the MCP
   endpoints as addresses the kernel's host reaches (`http://<app-host>:<port>`
   over the overlay, or the public https name), never loopback.
2. The application's way back: `OS_INTERNAL_URL` at the kernel's host
   (the internal API on the overlay address, admitted by address and by the
   application's token), `MALUDB_API_URL`, the hand-off token's check.
3. The application server's own platform services (gap 8): per-server role
   and database names on the database server, or a small local cluster for
   the vault and the gateway only.
4. `role: application-server` in first boot and the installer (no kernel
   units, the installer's host tools, enrolment before the install), the
   node kind, `proxy-config.sh` with an upstream per name, the boot test with
   three VMs.

## Open questions

1. **The office on the overlay after its first boot** (difference 1):
   answered by the owner 2026-11-12. The office keeps the LAN name for its
   own connection for good; TLS with the certificate verified protects it,
   and the overlay stays for the other members.
2. **Agents on the database server** (gap 7): answered by the owner
   2026-11-12. The database server is watched by three background agents:
   PostgreSQL, Linux and security. They run on the kernel's server and
   act on the database server through the estate if that can be achieved,
   which is the preferred design; the database server keeps what belongs
   with the data (the engine and its memory listener: memories are stored
   in PostgreSQL, so the memory service's data is there). To design with
   slice 3: what each agent reads (the node's report and its `database`
   part, logs and metrics over a read-only channel, `pg_stat_*` through a
   monitoring role), what it may do (the estate's node actions, each
   approved), and which of this needs a small collector on the database
   server that is not an agent.

The earlier planning questions: none were left open. The kernel-side design of application servers
(decision 4, slice 3) is written as its own note before slice 3 starts.
