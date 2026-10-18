# Phase 6, slice 1: the vault and the ledger

Delivered 2026-10-18 as package `maluos-vault` (0.1.0), with changes to
maluos-firstboot (0.1.5). It implements FR-7, FR-8, FR-12 to FR-19, FR-40,
FR-41 and FR-43 of docs/phase6-inference-gateway.md for secrets, and lays the
ledger the gateway writes model calls into from slice 2.

## What it is

One daemon, `maluos-vault`, socket-activated on `/run/maluos/vault.sock`,
running as the system user `maluos-vault` with no network and no privileges.
Callers speak HTTP/JSON over the socket; the daemon reads the peer's uid from
the kernel (SO_PEERCRED), so identity costs nothing to configure and cannot
be spoofed by environment variables. `sudo -u joseph maluctl secret show
openai` is joseph's call, with joseph's key.

| Piece | Where |
|---|---|
| Daemon | /usr/lib/maluos/maluos_vault.py, maluos-vault.service + .socket |
| Client library | /usr/lib/maluos/maluos_vault_client.py (`Vault()`), used by maluctl, the components, the gateway later |
| CLI | `maluctl secret ...` (plugin /usr/lib/maluos/maluctl.d/secret.py) |
| Metadata and ledger | tenant schema: maluos_compartment, maluos_secret, maluos_secret_grant, maluos_delegation, maluos_ledger (+ views maluos_ledger_mine, maluos_ledger_daily) from /usr/share/maluos-vault/schema.sql |
| Values | /var/lib/maluos-vault/blobs/<id>: AES-256-GCM, per-blob HKDF key from the master key |
| Master key | /var/lib/maluos-vault/master.cred: 32 random bytes encrypted by `systemd-creds encrypt`, bound to the name `maluos-vault.key`; pid 1 decrypts it into the service's credentials directory at start (`LoadCredentialEncrypted=`). Sealed to the TPM when the host has one, to the host key otherwise. |
| Configuration | /etc/maluos/vault.yaml: database, tenant (written by first boot), `brokers`, `identities` |
| First boot | component 40-maluos-vault (before the other components, so they can store their secrets) |

## The model

- **Identity.** Linux user → principal `user:<login>` unless `identities:` in
  vault.yaml maps the user elsewhere (a service user to `agent:...`). The
  principal must exist in `maludb_principal` and be enabled; first boot now
  creates `user:<login>` for every operator account, `maluctl principal add
  user:<name> --kind human` enrols later ones. uid 0 is an **operator**: it
  manages shared compartments and may read anything (it is root). A
  **broker** (a Linux user listed in `brokers:`, the gateway in slice 2) may
  send `X-MaluOS-Principal` to act on behalf of a principal; the ledger keeps
  both names.
- **Compartments.** A personal compartment is named after its principal and
  is created on the owner's first `add`; the owner has full rights in it.
  Shared compartments (`system`, created by first boot; `org`, departments,
  whatever operators create) have no owner: operators manage them, grants
  give access. A compartment can be locked (`maluctl secret compartment
  lock|unlock`); reads and uses against a locked compartment fail with 423
  and a ledger row. `lock_mode` records the intent (`always_unlocked`,
  `manual`, `login`); unlock-at-login integration is later work.
- **Grants.** Per secret, to a principal or to a scope (a principal holds a
  scope when it is its home scope or it has a live `maludb_principal_scope`
  grant). Two levels: `use` (a broker may apply the secret on the grantee's
  behalf; the grantee never sees the value) and `read` (the grantee may
  retrieve it). Grants can expire. Resolution of a bare name follows FR-13:
  the caller's own compartment first, then the compartments it holds grants
  in; an ambiguous bare name is refused with the candidates listed.
- **Rotation.** `rotate` stores a new value; with `--grace 24h` the previous
  value stays retrievable (`show --previous`) until the window closes.
  `expires_at` is enforced on read and use (410).
- **Ledger.** Every add, read, use, rotate, delete, grant, revoke, lock and
  every denial is a row with the principal, the Linux user and uid, the
  calling process (`comm@unit` from /proc), the broker if any, the secret,
  the level that allowed it and the reason when it did not. The table is
  append-only for everyone, including the tenant, through a trigger; the
  vault's role has INSERT and SELECT only and cannot read memory tables.
  `maluctl secret usage` reports by secret, user, principal, event or day;
  non-operators see only their own rows (and the view `maluos_ledger_mine`
  gives the same to a principal-bound SQL session).
- **Values never leave the blob store except on a permitted read.** They
  are not in the database, the journal, the ledger or error messages; the
  harness and the boot test grep for them.

## Using it

```
maluctl secret whoami
echo "$KEY" | maluctl secret add openai --provider openai --stdin      # into user:<me>
maluctl secret list
maluctl secret show openai
maluctl secret exec openai -- python3 app.py                             # OPENAI_API_KEY in the environment
maluctl secret rotate openai --grace 24h
sudo maluctl secret add system/anthropic --provider anthropic            # a shared key
sudo maluctl secret grant system/anthropic --to agent:research --level use
sudo maluctl secret grant system/anthropic --scope dept:3 --level read --expires 30d
maluctl secret usage --since 30d --by user
sudo maluctl secret usage --raw
```

`exec` requires `read` on the secret (the process receives the value); the
`use` level becomes meaningful with the gateway, which applies the secret
without handing it to the caller.

The components keep their provisioning credentials in `system` too
(`mc2dbd-token`, `pg-<tenant>-password`, `maludb-api-token`,
`business-os-admin-password`), so `sudo maluctl secret show
system/maludb-api-token` works and every read of them is in the ledger.
The files under /var/lib/maluos/secrets remain the runtime source for now.

## Wire protocol (for the gateway and other clients)

HTTP/1.1 over the Unix socket, JSON bodies, errors as
`{"error": code, "message": text}`.

| Method and path | Purpose |
|---|---|
| GET /v1/health, GET /v1/whoami | liveness; who the caller is |
| GET /v1/compartments, POST /v1/compartments, POST /v1/compartments/{name}/lock or /unlock | compartments |
| GET /v1/secrets[?compartment=&all=1], POST /v1/secrets | list; add (`upsert: true` rotates an existing one) |
| GET /v1/secrets/{ref}, DELETE /v1/secrets/{ref} | metadata (+ grants for managers); delete |
| GET /v1/secrets/{ref}/value?mode=read\|use&purpose=&previous=1 | the value; `mode=use` only for brokers and operators |
| POST /v1/secrets/{ref}/rotate, /grants, /revoke; GET /v1/secrets/{ref}/grants | rotation and grants |
| GET /v1/ledger?since=7d&secret=&principal=&event=&user=&limit= | the caller's rows (operators: everything) |

`{ref}` is `compartment/name` or a bare `name`, URL-encoded. Header
`X-MaluOS-Principal: <ref>` (brokers only) sets the effective principal.

## Tests

- `tests/vault-local-test.sh`: 66 checks on the development host against a
  throwaway database (no VM): two users with the same secret name and
  different values, cross-user denial, shared compartment and grants by
  principal and by scope, use versus read, the broker path and its refusals,
  identity mapping, rotation with and without grace, lock, expiry, delete,
  exec, the ledger's scoping and append-only rule, the vault role's limits,
  and that no value appears in the database, the blobs or the daemon log.
- `tests/qcow2-boot-test.sh`: on the booted image, the socket, the sealed
  master credential, peer-credential identity for the login user and root,
  the imported system secrets, a second user with their own key, a grant,
  ledger rows for reads and denials, and no value in the journal or the
  database.

## Decisions and limits

- Python stdlib HTTP server, one PostgreSQL connection per request: fine for
  a host-local secret store, measured in milliseconds; the gateway's hot
  path will not go through HTTP for every token.
- `use` by a non-broker is refused rather than treated as `read`, so a
  `use` grant can never leak a value before the gateway exists.
- Root is trusted: an operator reads any secret, with a ledger row. The
  threat model is the one in §8 of the requirements: the vault bounds what
  unprivileged users and agents can reach, not root.
- Export and import (encrypted to an operator key), delegation, alerts and
  the unlock-at-login mode are slice 4. A TPM-sealed master credential is
  not recoverable on another machine until then: keep that in mind before
  trusting the vault with the only copy of a key.
