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
in /etc/maluos/alert-hooks.d.

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

## Planned

- The default applications and the integration plugin as components.
- The ISO catalogue layers and the `maluctl component` selector.
