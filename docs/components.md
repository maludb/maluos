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

## Planned

- maluos-business-os: the kernel (PHP 8.5, Node 22, the Python MCP servers
  in a vendored virtual environment) with a module reproducing the docker
  install's bos-init natively; applications through the kernel's own
  installer, the defaults vendored for offline installs.
- The ISO catalogue layers and the `maluctl component` selector.
