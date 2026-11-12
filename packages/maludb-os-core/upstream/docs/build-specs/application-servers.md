# Application servers: the kernel half (db/194)

Built 2026-11-12 for MaluOS Phase 14 slice 3. The design and the owner's decisions are in the MaluOS repository,
`docs/phase14-application-servers.md`. Proof: `bin/test_application_servers.php` (33 checks).

An application may run on a MaluOS server of its own, apart from the kernel. That server joins the estate as a
node with a code its operator minted **for named applications**, and installs them with the same
`bin/app_install.php`, which then runs in two halves.

## The join code names the applications

- `desk_enrollment_codes.apps text[]`: the catalog keys a `server` code allows. `desk_code_mint(..., $apps)`,
  Settings → Desks' handler (`apps`), `php bin/mint_desk_code.php --kind server --apps hr,projects`.
- `node_join()` copies them to `locations.node_apps`, the node's allowance. A node whose code named none installs
  nothing (403 `not_allowed`).
- `locations.node_role` (`kernel`, `application-server`, `database-server`) and `locations.node_address` are
  labels: the kind stays `server`. Registration sets both for an application server.

## The installer's two halves

| Half | Runs on | As | Steps |
|---|---|---|---|
| host: `app_install.php apply <repo> --kernel <door> --node-token-file <f> [--address <a>]` with the usual `--db-*` | the application server | root | 1 to 7 (the code, the database as the database server's admin role, `config/.env`, the vhost, the units, the probe), then the relay vhost, the bundle, `register`, the job, the token into `config/.env` |
| kernel: `app_install.php apply <bundle> --half kernel --host-report <f> --result <f> --node-id <n>` | the kernel server, started by `register` | the web user | 8 to 16 (catalog, application, endpoints, token, roles, status, shares, the action registry, skills, approvals, grants, hires, health, sign-on) |

Without `--kernel` and `--half` the installer is what it was: both halves on one host.

What the kernel half takes from the host half is the **host report**: `base_url` (where the kernel posts the
application's actions), `address`, the port variables, which endpoints answered, whether the application
already holds a token. `$A` is the bundle, so every `$A/…` read (the registry, the skills, the job descriptions)
works on it. The application's row gets `location_id` = the node and `internal_base_url` = `base_url`; the
registry file's `base_url` is the same address instead of loopback.

The kernel half runs as the web user, so it cannot restart a unit: `docs/deploy/maludb-os-actions-reload.path`
watches `mcp/registries` and restarts the Actions MCP. `mcp/registries` must be writable by the web user on a
kernel that takes registrations.

## The three calls (node token; the door and the internal port only)

| Call | Answers |
|---|---|
| `POST /api/v1/estate/apps/prepare` `{key?}` | the node, its allowance, the operator's email, the domain and scheme, and `env`: `APP_HOST`, `ACTION_TOKEN_KEY`, `ACTIONS_RELAY_KEY`, `MALUDB_API_TOKEN`, the mail settings |
| `POST /api/v1/estate/apps/register` `{key, files, host, hire_agents, grant_standing_departments, source}` | 202 `{job}`; 403 `not_allowed`, 400 `invalid` (a loopback `base_url`, a path that leaves the bundle, a dot file, another application's manifest, more than 8 MB or 400 files), 409 `busy` |
| `GET /api/v1/estate/apps/job?id=` | `{state, exit, output, result}`; `result.application_token` once, with the first answer after the run ended |

The bundle is staged under `STORAGE_ROOT/app-installs/<node>-<key>-<time>-<random>/`, never under a web root.
None of the three is on the public allow-list. `prepare` answers the kernel's signing keys, as every
application's `config/.env` holds them today (the owner's decision 2026-11-12: the master key now, a key per
application later); it must never be made public.

## The applications' door

`docs/deploy/apache-react-cutover.conf` carries the door as commented lines (`#DOOR `): a vhost on the kernel
server's LAN address, port 8081, `Require ip` for the application servers, serving only what an application
calls (`directory`, `agents/chat`, `notify/sms`, `apps/read|mine`, `runs/facts`, `ledger/periods`, `health`), the
three calls above, `/maludb/` (the MaluDB API) and `/model/` (the model proxy). Everything else is refused. The
installer of the host (MaluOS's kernel component) fills `DOOR_ADDRESS` and `DOOR_CLIENTS` and removes the
prefix. The internal vhost on `127.0.0.1:8080` is unchanged.

A remote application's `OS_INTERNAL_URL` is the door and its `MALUDB_API_URL` is `<door>/maludb`.

## The relay on the application server

An application's deploy file binds its internal vhost to loopback. The host half leaves it so and writes
`/etc/apache2/sites-available/<key>-kernel-relay.conf`: a vhost on the server's own address, port = the
internal port + 1000, `Require ip` the kernel server's address, passing to the internal port. That address and
port are the `base_url` it reports.

## Not built here

- (built) Settings → Desks: the code form has the applications field for a server code.
- The node's report setting `node_role` for a kernel or a database server.
- `maluctl app names --upstreams`, the proxy's upstream per name (MaluOS).
- A key per application, TLS on the door and the relay (a later slice).
- The host half has run in `plan` mode against a test kernel only; its `apply` is proven by MaluOS's boot test.
