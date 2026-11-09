# MaluOS components

A component is something a MaluOS system can carry in addition to the base
memory server: the MaluDB API server, the Business OS kernel, its
applications. The model replaces Ubuntu's "featured snaps" step with
packages, so a component can be chosen at install time, requested at first
boot through cloud-init, or added later, and every path ends in the same
provisioned state.

## Anatomy

| Part | Where | Role |
|---|---|---|
| Metapackage `maluos-<name>` | seeds/<name>.seed -> packages/maluos-meta | What "the component" means in packages |
| Software packages | packages/<pkg> (vendored upstream + debian/) | The code, units, users, config |
| First-boot module | /usr/lib/maluos/components/<nn>-<name>.py, shipped by the package | Provisions the component against the database on first boot or `maluctl provision` |
| Configuration | /etc/maluos/firstboot.yaml `components.<name>` | enabled: true/false, component-specific keys |
| Checks | tests/qcow2-boot-test.sh | The component's acceptance checks on a booted image |

The first-boot engine (maluos-firstboot) runs the core steps, then every
module in /usr/lib/maluos/components in name order with a context (database
name, tenant, psql helper, secrets directory, env-file helpers). A module
returns a JSON summary that lands in /var/lib/maluos/firstboot/done and in
`maluctl status`; a failing module is recorded and does not block the rest.
Modules must be idempotent: `maluctl provision --force` re-runs them all.

## Delivery paths

- **Image profile**: image/profiles/server.pkgs lists what the server rootfs
  carries (today: maluos-server, maluos-api, maluos-business-os and
  maluos-apps). A profile per variant, or a squashfs layer per component in
  the ISO catalogue, gives install-time choice.
- **cloud-init / autoinstall**: write /etc/maluos/firstboot.yaml with the
  components wanted; packages already in the image are provisioned, absent
  ones are installed from the on-media repository first (planned).
- **Later**: `apt install maluos-<name>` then `maluctl provision --force`
  (planned: `maluctl component add <name>` doing both).

## Components today

### maluos-vault (package maluos-vault, in maluos-server)

The secret vault of Phase 6 slice 1 (docs/phase6-slice1-vault.md): a
socket-activated daemon with peer-credential identity, per-principal
compartments, grants, and the append-only ledger in the tenant schema.
Component 40-maluos-vault runs before the others and gives them
`ctx["store_secret"](name, value, kind=, provider=, env_var=)`, which keeps
a copy of a provisioning credential in the shared `system` compartment.
Seals the master key with systemd-creds (TPM when present), creates the
vault's database role and tables (including `maluos_record_episode`, the
daemons' only path into memory), starts the socket, imports the listener
token. Slice 4 adds delegation, export/import and alerts
(docs/phase6-slice4-operations.md).


### maluos-gateway (package maluos-gateway, in maluos-server)

The inference gateway of Phase 6 slice 2 (docs/phase6-slice2-gateway.md):
OpenAI and Ollama APIs on a socket, the GPU scheduler, the catalogue of
tiers and aliases, the engine queue worker. Component 45-maluos-gateway
creates the role and tables, seeds the catalogue when empty, registers the
MCP tool maluos.model_status, makes the gateway a vault broker, starts the
socket, and optionally installs Ollama and pulls models (ollama.install /
ollama.pull in /etc/maluos/gateway.yaml or components.maluos-gateway.ollama
in firstboot.yaml). Cloud rungs, budgets and alerts are in slices 3 and 4
(docs/phase6-slice3-routing.md, phase6-slice4-operations.md); alert hooks go
in /etc/maluos/alert-hooks.d. From 0.4.0 (Phase 13 G2) the gateway is also
an inference node of the MaluOS network (docs/inference-node-api.md): the
node API /node/v1 for the Sovereign LLM Manager, inference and node keys,
the Anthropic face, async jobs, and the `remote` backend kind that pairs a
desk with a shared GPU host (`maluctl gateway key issue`, `expose`,
`backend add NAME URL --key`); the component also enrols the gateway's own
principal user:maluos-gateway, which holds the pairing keys.

### maluos-agent (package maluos-agent, in maluos-server)

`maluctl agent` (docs/agents.md): agents as system entities. No first-boot
module; it acts on a provisioned host.

### maludb-api (package maludb-api, metapackage maluos-api)

The MaluDB Python API server (github.com/maludb/maludb-python-api-server),
vendored at a pinned commit by scripts/vendor-maludb-api.sh and packaged
against Ubuntu's own python3-fastapi, uvicorn, psycopg, httpx and
cryptography. Runs as user maludb-api on 127.0.0.1:8000 under a hardened
unit; config in /etc/maludb/maludb-api.env; auth store in
/var/lib/maludb-api; logs in /var/log/maludb-api. The embedding, skill
reindex and memory reindex sweeps are timers, enabled by first boot.

First-boot module 50-maludb-api: gives the tenant role a password (kept in
/var/lib/maluos/secrets/pg-<tenant>.password; the API connects over TCP with
scram), seals the auth store with a generated MALUDB_STORE_KEY, restarts the
service, mints the tenant's API token (/var/lib/maluos/secrets/api.token,
`sudo maluctl token api`), and writes the token into the sweep env files.

### maludb-os-core (package maludb-os-core, metapackage maluos-business-os)

The MaluDB Business OS kernel (github.com/maludb/maludb-os-core), vendored
at a pinned commit by scripts/vendor-maludb-os-core.sh. Route B, native:
no container. The package builds the Composer dependencies, the Next.js
front end and the Python virtual environment for the MCP servers and the
agent runner at package build time (network needed then, not at install),
and installs the kernel in /var/www as upstream expects, the eight systemd
units disabled, the runner sandbox (bos-runner and bos-agent users,
/usr/sbin/bos-agent-exec with its sudoers line), the PHP upload limits for
whichever PHP Apache runs, and the localhost-only :8080 listener.

Runtimes on Ubuntu 26.04: PHP 8.5 (the kernel lints clean and its Composer
constraints admit it), Node 22, Python 3.14 (every requirement has wheels).

First-boot module 60-maludb-os-core, a native port of maludb-os-docker's
bos-init with PostgreSQL, the engine and the MaluDB API local:

1. the kernel's own names (<domain>, www, os, app) so its URLs resolve on
   this host: on loopback under http (Apache answers there); under https
   at `proxy_address` (the proxy as the office sees it) in a marked block
   of /etc/hosts and off every loopback line, since nothing on the office
   serves https on loopback, or no line at all when no address is given,
   which the summary (`hosts.mode: none`) says (2026-11-05,
   docs/phase13-estate-behind-a-proxy.md, part 2); the applications'
   names join the block after step 8;
2. the kernel's activity memory: database maludb_os_memory, role and schema
   maludb_os_mem, memory schema enabled, a MaluDB API token minted for it;
3. the kernel database maludb_os and every migration in order, with a
   resumable ledger in /var/lib/maluos/business-os;
4. passwords for app_rw, app_records_ro, app_activity_ro and app_runner;
5. config/.env, web/.env.local and /etc/business-os/runner.env rendered
   from generated secrets (kept under /var/lib/maluos/secrets/business-os);
6. the Apache vhosts rendered for the domain, the web drop-in, the units
   enabled, the PHP API health-checked;
7. the first super-admin (password generated unless configured), the first
   model registry row, the cron jobs, the kernel's Installer and JEV agents.


Status 2026-10-18: boot test PASS (44 checks) on the cloud image under
QEMU/TCG: first boot provisions the kernel end to end (memory database,
API token, kernel database with all 184 migrations, Apache vhosts, the
eight units, the first super-admin, model row, cron, the kernel's agents);
the PHP API, the login page through Apache, the landing page, the four MCP
servers and the agent runner with its three harnesses all answer. Under
emulation provisioning takes about 25 minutes (the first-boot unit allows
two hours; provisioning resumes on the next boot if interrupted); under KVM
it is a couple of minutes.

8. the applications (the maluos-apps proposal, phase 1; 2026-11-05): for
   every key in `apps.install` (default `[hr, projects, helpdesk, spaces]`,
   HR first because it is the one application that writes the directory;
   `[]` installs none), the kernel's own installer, `bin/app_install.php
   apply https://github.com/maludb/maludb-os-<key>.git --by <admin_email>
   --domain <domain> --scheme <scheme> --grant-standing-departments`, plus
   `--hire-agents` unless the key is in `apps.propose_agents`, `--ref`
   when `apps.ref` names one, and `--proxy-address` under https when the
   component has one (the application's name goes to the proxy in
   /etc/hosts, not to loopback), as root from /var/www, in the listed order.
   A marker per application under /var/lib/maluos/business-os/apps (the
   installer's output beside it as `<key>.log`) means a re-run reconciles
   rather than repeats; a failing application is logged and the next
   continues. The step waits for DNS and HTTPS to github.com first (the
   clone needs both; a first boot can reach network-online before a route
   is up). The summary gains `apps: {installed, failed, errors}` and
   `names`, the DNS names the office needs, which `maluctl status` prints.
   The host tools the builds need come from the metapackage maluos-apps.

Settings in firstboot.yaml under components.maludb-os-core: domain, scheme,
proxy_address (https only), admin_email, admin_name, admin_password, model_key, model_name,
model_provider_id, anthropic_api_key, openrouter_api_key, malumail_api_key,
and `apps` with `install`, `ref` (key to git tag or branch) and
`propose_agents` (the conffile's commented block shows the defaults).

`maluctl app names` (a maluctl.d plugin shipped by maludb-os-core) prints
the names the office needs, one per line: the bare domain, www, app, os,
and `<vhost.label>.<domain>` for every application in /srv/apps whose
maludb-os.json it finds; the domain from the first-boot state. The proxy's
operator pastes them. `maluctl app add|update|status|list|remove` and the
installer's First boot screen are phase 2 of the proposal; packaged
applications (`maludb-os-<key>` debs, so an offline ISO installs an office
with its applications) phase 3; `remove --purge` and the names in the
estate's node report phase 4.

Not yet in this component: the integration plugin; the Claude CLI for the
agent harness; Hermes.

### maluos-apps (seeds/apps.seed; the maluos-apps proposal, phase 1)

A metapackage only: the host tools every Business OS application's build
needs on top of maluos-business-os (composer, python3-venv, python3-pip,
poppler-utils for DocCloud's pdftotext, unzip, git). In the server image
beside maluos-business-os; on the medium's catalogue like every seed. The
provisioning is the kernel component's step 8 above (components.maludb-os-core.apps);
the applications are cloned from github.com/maludb/maludb-os-<key> at first
boot, so an office needs the network then, until phase 3 packages them.

Status 2026-11-05: built, unit-tested (tests/apps-test.py: the apps block,
the install loop against a fake installer, the names from two manifests,
the plugin). The acceptance checks in tests/qcow2-boot-test.sh run when the
seed leaves the applications on (`BOOT_TEST_APPS=1`; CI's seed sets
`apps.install: []`, since four clones and builds take long under TCG): on
the owner's dev host, an office with hr, projects, helpdesk and spaces
active after first boot and `maluctl app names` listing eight names.

### maluos-office-setup (package maluos-office-setup, in maluos-business-os)

Not a component (no first-boot module): the Claude Code plugin that configures an office's Business
OS after first boot, vendored at a pinned ref of github.com/maludb/maluos-office-setup under
/usr/share/maluos/claude-plugins/maluos-office-setup, with a local marketplace at
/usr/share/maluos/claude-plugins (`/plugin marketplace add` that directory), the sudoers rule that lets
members of sudo run exactly the plugin's scripts as root without a password, the launcher
/usr/bin/maluos-office-setup and `maluctl office-setup run|shell|check|status|providers` (run installs
Claude Code for the operator with Anthropic's native installer, as the desktop's Tools Installer does).
The plugin's scripts read the kernel component's features (proxy_address since 0.1.16, apps.install since
0.1.15) and drive `maluctl provision --force`; nothing in the component changes for it. In
seeds/business-os.seed, so every server image with the kernel carries the plugin. The operator's path is
the handbook's 10-office-configuration.md; the package proposal 23-office-setup-package.md.

The whole of it, phase by phase, with the scripts' reads and writes and the two ways an office gets its
configuration (the installer's First boot screen or this interview): docs/office-setup.md.

Status 2026-11-09: packaged (packages/maluos-office-setup, scripts/vendor-maluos-office-setup.sh), built and
lintian-checked on the development VM, maluos-meta 0.2.18 regenerated so maluos-business-os depends on it;
not yet run on an office from the package, not yet on an image or on apt.maluos.com (the next build).

### maluos-apple-t2 (seeds/apple-t2.seed; the Apple T2 round, docs/phase11-apple-t2.md)

Hardware support rather than software: what an Intel Mac with the T2 chip
needs beyond Ubuntu 26.04's kernel. The T2 bridge driver (apple-bce-dkms,
built from source), the SMC and trackpad drivers patched for the T2
(vendored t2linux DKMS packages), DKMS with the kernel headers so kernel
updates rebuild them, the T2 audio profiles, Vulkan for the Radeon; as
recommends the Touch Bar function row (tiny-dfr), the fan daemon
(t2fanrd), the firmware script and the APFS driver; the PipeWire DSP
(t2-dsp) is in the repository, off the medium. maluos-apple-t2-support adds the import of the Mac's own Wi-Fi and
Bluetooth firmware (maluos-apple-firmware), gates the daemons to Apple
hardware and puts the bridge driver in the initrd. No first-boot module:
nothing to provision. The installer adds the component itself on a T2 Mac
when the medium carries it; the medium carries the component's Ubuntu
dependencies in /maluos/apt/extra so the install is offline.

### maluos-nvidia (seeds/nvidia.seed; Phase 13 shared GPUs, docs/phase13-shared-gpus.md)

The NVIDIA driver for an RTX card in a MaluOS box: the Canonical-signed
kernel modules for the generic kernel first (`linux-modules-nvidia-595-generic`,
so Secure Boot needs no MOK enrolment and no DKMS build), the 595 driver
branch with 580 as the alternative for a card the newer branch dropped,
nvidia-smi (what `maluctl gpu status`, the session's host state and the
System Monitor's GPUs tab read) and nvtop as a recommend. Ollama brings its
own CUDA runtime, so no toolkit. No first-boot module: the driver loads at
the next boot. The installer adds the component itself on a machine with an
NVIDIA card (maluos-installer 0.3.4; `components.install`, derived like the
Apple one, `remove` refuses it): from the medium's extra pool when the medium
carries the driver, else from the network before the first boot, and when
the network is down it is left out with a warning and
`sudo apt install maluos-nvidia` adds it later. A DGX Spark is arm64 and is
not a MaluOS device (the local LLM server runs there); an RTX card in an x86
box is the MaluOS case. A host without the driver, or with an AMD or Intel
GPU, is read through /sys/class/drm instead, with fewer numbers.

### maluos-estate (package maluos-estate, in maluos-server and maluos-desktop; Phase 13 slice 1, docs/phase13-slice1-nodes.md)

A MaluOS host as a node of its estate. `sudo maluctl estate join URL
--code CODE [--kind server|inference]` exchanges a one-time node code for a
node token, makes the host principal `host:<hostname>` (kind service) and
maps the system user maluos-estate to it in vault.yaml and gateway.yaml,
keeps the token and an ed25519 node key in that principal's vault
compartment, writes /etc/maluos/estate.yaml (no secret) and starts
maluos-estate.service: presence and facts every `heartbeat_s`, the report
every `report_s` (units, agents, the gateway, the vault's alert rows,
updates, disk, memory, load), `offline` on a clean stop. `maluctl estate
status|report|nodes|leave`; a desk's node record is its desk row (`--kind
desk` runs `maluctl office enroll`). The package also carries the shared
estate client `maluctl office` uses and the mock office the tests run,
which stands in for the kernel's estate endpoints (db/188, db/189 and
db/190, built 2026-10-28) in the image tests.

Delegation (slice 2, docs/phase13-slice2-delegation.md): the package
carries the envelope module (`maluos_estate.envelope`: a signed JSON
object naming the originator, the sender, the chain, the target and the
authority; ed25519 with the node's key or the desk's); maluos-estated
registers the node's agents (`/etc/maluos/agents/*.manifest.yaml`, written
by `maluctl agent create`) in the office's directory, caches the members'
public keys in `/run/maluos/estate/keys.json`, long-polls the node's inbox
at the office and runs each task through the agent's socket with its
envelope (maluos-agent verifies it and applies the agent's own policy),
posting the result with its provenance back; an operator's action
(`restart_agent`, `start_agent`, `stop_agent`, `apply_updates`; `reboot`
when allowed) runs under a polkit rule. `maluctl estate
agents|tasks|keys|inbox|actions`.

The overlay (slice 1b, docs/phase13-slice1b-overlay.md): the join makes
the host's WireGuard key (the private half in the vault as
`estate-overlay-key`), the office gives it an address in the estate's
range and a name (`NAME.internal`), and maluos-overlay.service, a root
reconciler with CAP_NET_ADMIN, keeps the `estate` interface, the tunnel to
the hub (or, on the hub, `join --hub HOST:PORT`, every spoke, with
forwarding on the interface only) and the names in /etc/hosts, refreshed
from `endpoints.overlay` every minute and at once on a heartbeat's
`overlay_changed`. `maluctl estate overlay status|peers|up|down|rotate|
refresh`; `--no-overlay` opts a host out; `maluctl gateway expose --bind
overlay` puts the node API on the estate's network only.

## A database on another server (Phase 14)

Every component above reaches PostgreSQL through first boot's connection
(`ctx["psql"]`, `ctx["psql_file"]`, `ctx["exists"]`), so the same code
provisions the host's own cluster as the local superuser or, with a
`database_server` block in firstboot.yaml, a MaluOS database server as its
admin role over TLS (docs/phase14-database-server.md). What a component
may rely on:

| ctx key | Meaning |
|---|---|
| `psql(sql, db)`, `exists(sql, db)` | a statement on the database, wherever it is |
| `psql_file(path, db, pre=None, check=True)` | a file of SQL (a schema, a migration) through the same connection; `pre` runs first in the session (`SET ROLE …`). Never `runuser -u postgres psql -f` |
| `ensure_maludb_database(name)` | a database with the engine in it: created with its extensions locally, copied from the server's template remotely. True when it was created |
| `database_target` | None for the local cluster, else `{host, port, admin, sslmode, ca}`: what to write into a configuration that names the database's host |
| `service_login(role, password_file=…, owner=…)` or `(role, vault_ref=…)` | `{}` locally (the socket, peer authentication). Remotely the role gets a password and the call returns the keys for the service's configuration: `pg_host`, `pg_port`, `pg_sslmode`, `pg_sslrootcert`, `pg_user` and `pg_password_file` or `pg_password_ref` |

On a database server the admin role is not a superuser: a component must
not `CREATE EXTENSION` an untrusted extension, `ALTER SYSTEM`, or create a
SUPERUSER role. With `role: database-server` no component runs at all.

## Planned

- The default applications as packages (maluos-apps phase 3), `maluctl app`
  (phase 2) and the integration plugin as a component.
- The ISO catalogue layers and the `maluctl component` selector.
