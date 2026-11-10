# The landscape: what each repository is, and where they overlap

This is the repository map for installation, refreshed November 9, 2026.
Use the [current release baseline](02-current-release.md) with the table;
historical reconciliation findings are distinguished from current packaging.

## The repositories that matter for an install

| Repository | What it is | Role in the install path |
|---|---|---|
| `maluos` | The Linux distribution: Ubuntu 26.04 derivative. Signed apt repository (apt.maluos.com), metapackages from `seeds/`, the installer, the ISO and image builds, first-boot provisioning, the vault, the gateway, the estate client, the desktop | The packaged operating-system path; external ARM inference hosts retain their vendor OS |
| `maludb-core-26` | The MaluDB memory engine: a PostgreSQL 18 extension in C, plus the MC2DB listener, REST and realtime services, drivers. For Ubuntu 26.04 | Vendored into `maluos` as two debs (`postgresql-18-maludb-core`, `maludb-mc2dbd`) under `vendor/maludb/`. Never built by hand on MaluOS |
| `maludb-core` | The same engine for Ubuntu 24.04 and PostgreSQL 17 | Not used on MaluOS. The kernel's hand-install runbook and the docker install clone it |
| `maludb-python-api-server` | The MaluDB API (REST and MCP on :8000) | Packaged in `maluos` as `maludb-api`, metapackage `maluos-api` |
| `maludb-os-core` | **The Business OS kernel**: estate, people, agent workforce, single sign-on, directory API, approvals. Runs no business application itself | Packaged in `maluos` as `maludb-os-core`, metapackage `maluos-business-os`, provisioned by first-boot component `60-maludb-os-core` |
| `maludb-os-hr`, `-projects`, `-helpdesk`, `-spaces` | The four default applications | Installed beside the kernel by `bin/install_default_applications.sh` from GitHub |
| `maludb-os-doccloud` and the other `maludb-os-*` | Applications installed on request | Installed by `bin/app_install.php apply <repo>` |
| `maludb-os-docker` | The kernel plus Help Desk and Spaces as one privileged systemd container on an Ubuntu 24.04 hosting VM | **Not on this path.** Its first-boot script was ported natively into `maluos` |
| `maluos-local-llm-server` | Intended inference node service for machines outside MaluOS (Apple Silicon Mac, DGX Spark); scheduler/store implemented, runnable service pending as reviewed November 9, 2026 | [ARM host preparation and integration requirements](11-arm-inference.md); the packaged gateway remains the node implementation on MaluOS |
| `maludb-os-sovereign-llm-manager` | A Business OS application that manages a fleet of inference nodes | Optional application; later |
| `maludb-os-htmx-php-guidelines`, `maludb-os-integration` | Claude Code plugins that say how an application is built and how it fits the kernel | For developers, not operators |

## Three names that get confused

1. **maludb-core-26 is not the Business OS.** It is the database engine.
   The Business OS kernel is `maludb-os-core`. The name prefix `maludb-os-`
   marks the kernel and its applications; `maludb-core` marks the engine.
2. **"MaluDB" means three things.** The engine (the extension), the API
   server (the Python service in front of it), and the company. In
   `firstboot.yaml` the engine is simply there; the API is the component
   `maludb-api`; the kernel is the component `maludb-os-core`.
3. **"Office" and "estate".** The office is the server that runs the
   kernel. The estate is the kernel's model of every machine that joined
   it: desks (desktops), servers, inference nodes. A desk *enrols* with an
   office; a server *joins* the estate; both use a one-time code minted at
   the office.

## The overlaps

### The kernel can be installed three ways, and they exclude each other

| Path | Where it is written | Host it assumes | Status for us |
|---|---|---|---|
| By hand | `maludb-os-core/docs/install.md` (and the hosting-VM edition beside it) | Ubuntu 24.04, PostgreSQL 17 from `maludb-core`, PHP 8.3, Node 24, the code cloned to `/var/www` | A developer's path on plain Ubuntu. Wrong on MaluOS: different Ubuntu, different PostgreSQL, and the packages already did it |
| Docker | `maludb-os-docker/host-install.sh` | Ubuntu 24.04 hosting VM with PostgreSQL 17 on the host, the kernel in a privileged container | Excluded by decision; see [20-reconciliation.md](20-reconciliation.md) |
| MaluOS native | `maluos/packages/maludb-os-core` and the first-boot component `60-maludb-os-core.py` | MaluOS server (Ubuntu 26.04, PostgreSQL 18, PHP 8.5, Node 22) | **The path these documents use** |

Use the native handbook path on MaluOS. Older hand-install instructions
must not clone a second engine and kernel over the packaged ones.

### The server carries the kernel; office provisioning is opt-in

Current `firstboot.yaml` sets `maludb-os-core.enabled: false`. The First
boot screen can enable it with domain, scheme, proxy address and admin,
or [office setup](10-office-configuration.md) can do so afterwards. The
[unattended plan](10-office-unattended.md) supplies the same configuration.
A new GPU-only host leaves it off. The placeholder office on every server
was a 26.04.20261102 behavior; the GPU guide retains cleanup for old hosts.

### The engine's README installs from the wrong checkout

`maludb-core-26/README.md` Quickstart step 1 clones `maludb-core` and
then changes into `maludb-core-26`, which that clone did not create. The
rest of the Quickstart then runs against the Ubuntu 24.04 tree. On MaluOS
none of it applies: the engine arrives as a deb and first boot creates
the database, the extension and the tenant.

### Applications are cloned from GitHub at install time

`bin/app_install.php` clones each application to `/srv/apps/<key>`, runs
`composer install`, makes a Python venv, writes its vhost and units and
registers it with the kernel. Current `maluos-apps` packaging carries the
build tools and the Business OS component invokes the installer at first
boot. When enabled, it installs HR, Projects, Help Desk and Spaces by
default; `apps.install` selects a different list, or `[]` defers all.
GitHub/dependency access is still needed for these runtime installs.
[Applications](12-applications.md) covers inspection and later installation;
[the original proposal](21-maluos-apps.md) is retained as design history.

### Three designs for "a queue in front of a GPU"

The gateway (`maluos`), the node service (`maluos-local-llm-server`) and
the Sovereign LLM Manager overlapped until 2026-10-25, when the owner
decided: one node API (`docs/inference-node-api.md` in `maluos`), two
implementations (the gateway on MaluOS, the node service elsewhere), one
manager over both. That decision stands; nothing here reopens it. For
this test the GPU server is MaluOS, so only the gateway is involved.
The [ARM extension](11-arm-inference.md) covers runtime preparation on
other operating systems. Its source review found that the standalone
service has not yet implemented that shared HTTP contract; the older
design is not an installation guide.

### The docs themselves

`maluos/docs/` is an engineering journal: a plan, a roadmap of build
tasks, and one document per phase and slice, each with a Status section.
`maludb-os-core/docs/` is the same for the kernel. Neither says, in one
place, "do this, then this" for an operator with three machines. The
closest is `maluos/docs/phase13-three-machine-proof.md`, which the
runbooks here extend with the applications and the second desks.

