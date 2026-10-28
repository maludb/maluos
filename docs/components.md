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
  carries (today: maluos-server and maluos-api). A profile per variant, or a
  squashfs layer per component in the ISO catalogue, gives install-time choice.
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

1. loopback names for <domain>, www, os and app so the kernel's own URLs resolve;
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

Settings in firstboot.yaml under components.maludb-os-core: domain, scheme,
admin_email, admin_name, admin_password, model_key, model_name,
model_provider_id, anthropic_api_key, openrouter_api_key, malumail_api_key.

Status 2026-10-18: boot test PASS (44 checks) on the cloud image under
QEMU/TCG: first boot provisions the kernel end to end (memory database,
API token, kernel database with all 184 migrations, Apache vhosts, the
eight units, the first super-admin, model row, cron, the kernel's agents);
the PHP API, the login page through Apache, the landing page, the four MCP
servers and the agent runner with its three harnesses all answer. Under
emulation provisioning takes about 25 minutes (the first-boot unit allows
two hours; provisioning resumes on the next boot if interrupted); under KVM
it is a couple of minutes.

Not yet in this component: the default applications (Help Desk, Spaces,
HR, Projects) and the integration plugin, which the kernel installs from
git; the Claude CLI for the agent harness; Hermes. These follow as the next
slice, vendored for offline installs.

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
the next boot. Not on the install medium (the pool would grow by ~400 MB for
every medium): the installer offers it from the network and
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
which stands in for the kernel's estate endpoints (db/188 and db/189,
built 2026-10-28) in the image tests.

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

## Planned

- The default applications and the integration plugin as components.
- The ISO catalogue layers and the `maluctl component` selector.
