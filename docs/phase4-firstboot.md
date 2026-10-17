# Phase 4: first-boot provisioning

A freshly installed or freshly booted MaluOS server must come up with a
working memory database, not just the packages. maluos-firstboot does that
once, on the first boot, from a declarative file, and maluctl exposes the
result.

## What first boot does

`maluos-firstboot.service` (oneshot, after PostgreSQL and cloud-init's
config stage, before cloud-final) runs `/usr/lib/maluos/firstboot`, which:

1. waits for PostgreSQL 18;
2. creates the `maludb` database with the `vector` and `maludb_core`
   extensions and sets its search_path;
3. creates the tenant: a PostgreSQL role and schema (default `maluos`)
   with `maludb_user` granted and `enable_memory_schema()` run as the tenant;
4. upserts the administrator principal (default `human:admin`, home scope
   `org`) with `maludb_principal_upsert`;
5. prepares the MC2DB listener: a PostgreSQL role named after the OS user
   the packaged unit runs as (read from the unit, so the `maludb-mc2dbd`
   vs `maludb_mc2dbd` mismatch in the upstream package is harmless), the
   listener grants from maludb-core's bootstrap, a generated bearer token
   written to /etc/maludb/maludb-mc2dbd.conf and
   /var/lib/maluos/secrets/mc2dbd.token (root, 0600), then enables and
   starts the unit and waits for `/healthz`;
6. gives every human account a PostgreSQL superuser login (peer auth) with
   the tenant schema on its search_path, so `psql -d maludb` just works;
7. writes /var/lib/maluos/firstboot/done (JSON summary), which the unit's
   ConditionPathExists checks on later boots and the motd reads.

Every step inspects state before acting, so `maluctl provision --force`
re-runs the whole thing safely, and the same code path will carry future
upgrades (re-running `enable_memory_schema` is the documented upgrade step).

## Configuration

/etc/maluos/firstboot.yaml, a conffile with documented defaults: database
name, tenant name, admin principal (ref, kind, display name, home scope),
listener (enabled, host, port, token policy), operators (auto or a list).

cloud-init user-data can replace it before the service runs:

```yaml
#cloud-config
write_files:
  - path: /etc/maluos/firstboot.yaml
    content: |
      tenant: {name: acme}
      admin_principal: {ref: human:ops, kind: human, display_name: Ops, home_scope: org}
      listener: {enabled: true, host: 0.0.0.0, port: 5329, token: generate}
```

The same file works for ISO installs: subiquity's autoinstall can write it
with `write_files` under `user-data`, or a late-command can drop it in
/target/etc/maluos/.

## maluctl

```
maluctl status                  provisioning summary, extension version, listener health
sudo maluctl token [rotate]     print or rotate the listener bearer token
sudo maluctl principal list
sudo maluctl principal add agent:44 --kind agent --name Sasha --home agent:44
sudo maluctl provision [--force]
```

## Agent enrollment, as of this phase

An agent needs two things: the listener URL and the bearer token. Both are
on the box (`maluctl status`, `sudo maluctl token`), and a principal for the
agent is one `maluctl principal add` away. Binding a token to a principal
per request (so the listener sets `maludb_core.principal_ref` for the
caller) is the listener's job and is the next step on the agent-identity
track in Phase 6.

## Test

tests/qcow2-boot-test.sh now also checks, over SSH on the booted image:
the unit's result, the done file, the database and extension, the tenant
schema, the admin principal, the listener unit and `/healthz`, the token,
an MCP `tools/list` call with the token, operator peer login, and
`maluctl status`.

## Status (2026-10-17)

PASS on the cloud image under QEMU/TCG (BIOS): first boot provisioned
maludb (maludb_core 0.106.0), tenant `maluos`, principal `human:admin`,
listener role `maludb-mc2dbd` with token, operator login for the
cloud-init user; maludb-mc2dbd active, /healthz ok, MCP tools/list with the
bearer token returns tools; `maluctl status` reports everything. Lesson:
the rootfs build chroot shares the host network, so pg_createcluster
picked port 5433 when the host ran PostgreSQL; the build now pins 5432 and
first boot reads the real port from pg_lsclusters.

## Open

- A man page for maluctl.
- Principal-bound tokens in the listener (per-agent credentials).
- Model gateway (maludb_modeld) provisioning, once a model policy exists.
- Backup and key custody for the per-database master key the engine keeps.
