# Desk enrolment: a MaluOS desktop joins a Business OS office

Phase 12 slice 6. A MaluOS desktop is the estate's *desk*: the machine a
person works at. The office is a MaluOS server running the Business OS
kernel (maludb-os-core), whose estate already models a desk as a location
of kind `desk` with an owner, an enrolment token, presence and a last-seen
time (kernel `db/043`, `db/069`). This document is the contract between the
two and the MaluOS side of it. The kernel side is specified for the owner's
approval in the kernel repository, `docs/build-specs/desk-enrolment.md`;
it was approved and built the same day; the desk side is also proven
against a mock office that implements this contract
(`python3 -m maluos_desk.mock_office`).

## What enrolment does

```
sudo maluctl office enroll https://app.example.com --code 7F3K-2Q9M [--name "Ed's desk"]
```

1. The person obtains a one-time **enrolment code** from the office (their
   settings page, or an operator's `bin/mint_desk_code.php`), so no
   password is ever typed into a terminal and no long-lived credential is
   copied by hand.
2. The desk posts the code and its facts to the office; the office makes
   the desk location, owned by the person the code was minted for, and
   answers with a **desk token** and the office's endpoints.
3. The token goes into the person's own vault compartment as
   `office-desk-token` (kind token, provider office). It is never written to
   a file; `/etc/maluos/office.yaml` records everything else.
4. The office's **model endpoint** becomes a rung of the desk's gateway:
   backend `office` (kind `openai_compat`, secret `office-desk-token`), tier
   and alias `office`. A call with `--model office` goes to the office's
   ledger proxy with the person's desk token, applied by the gateway on the
   caller's behalf; the person never sees it and an agent uses it only
   under a delegation (`maluctl secret delegate --to agent:NAME --secret
   office-desk-token`) and an egress ceiling of at least `internal` (the
   gateway treats the office as a cloud rung: `sudo maluctl gateway policy
   set --principal agent:NAME --egress internal`). The office's rules hold:
   no provider key on a desk, every call in the office's prompt ledger, the
   office's budget.
5. `/etc/maluos/office.env` names the office's endpoints for every
   `maluos-agent@` unit (`MALUOS_OFFICE_*`). An agent that should reach the
   office's records, activity or memory MCP servers needs the token itself:
   `maluctl secret grant office-desk-token --to agent:NAME --level read`,
   a decision the owner makes per agent.
6. The session service heartbeats the office while the person is signed
   in (`presence: online`, every `heartbeat_s`), and says `offline` when it
   stops. The office's estate shows the desk, who owns it, and whether it
   is online. A desk the office retires answers 410 to the next heartbeat;
   the session tells the person, and `sudo maluctl office leave` cleans up.

## The contract, surface 1

JSON over HTTPS on the office's person face (`app.<domain>`), versioned by
`surface` in every request and answer. Errors are `{"error": code,
"message": text}` with the HTTP status.

| Method and path | Auth | Purpose |
|---|---|---|
| `POST /api/v1/desks/enroll` | the code in the body | register this desk; mint its token |
| `POST /api/v1/desks/heartbeat` | `Authorization: Bearer <desk token>` | presence and facts; the office may answer with new endpoints |
| `GET /api/v1/desks/me` | bearer | the desk, its owner and endpoints (no presence change) |
| `POST /api/v1/desks/leave` | bearer | retire the desk; the token is revoked |
| `GET /api/v1/desks/apps` | bearer | the office's MaluApps catalogue for this desk (Phase 12 slice 7; `endpoints.apps` in the enrol and `me` answers; `null` when the office publishes none) |
| `GET /api/v1/desks/agents` | bearer | the office's agents this desk may use (Phase 12 slice 8; `endpoints.agents`; `null` when the office publishes none) |
| `GET …/agents/ID/activity` | bearer | one agent's recent activity as the desk's owner may see it (the agent entry's `activity` URL) |
| `POST …/agents/ID/tasks` | bearer | the agent's task interface: JSON-RPC `agent/card`, `tasks/send`, `tasks/get`, `tasks/list` (the entry's `tasks` URL; maluos_agent_tasks) |

**Enroll request**

```json
{"surface": 1, "code": "7F3K-2Q9M", "name": "Ed's desk", "principal": "user:ed",
 "hostname": "ed-laptop", "os_platform": "linux", "os_release": "MaluOS 26.04.20261022",
 "variant": "Desktop", "app_version": "maluos-desk 0.1.0", "mcp_surface_version": "1",
 "cpu_cores": 8, "memory_mb": 15870, "storage_gb": 195, "machine_id": "<sha256 of /etc/machine-id, 32 hex>"}
```

`name` is optional (the office defaults to "<owner>'s desk"); `principal`
is the desk-local principal the token will be delegated to, recorded by the
office as the desk's `external_ref`. The facts fill `hostname`,
`os_platform`, `app_version`, `mcp_surface_version`, `cpu_cores`,
`memory_mb`, `storage_gb` on the location row; `machine_id` lets the
office recognise a re-enrolment of the same machine.

**Enroll answer** (201)

```json
{"surface": 1,
 "desk": {"id": 42, "name": "Ed's desk", "status": "active"},
 "office": {"name": "Subello", "url": "https://app.subello.com"},
 "owner": {"member_id": 1, "email": "ed@example.com", "display_name": "Edward Honour"},
 "token": "desk_…",
 "endpoints": {"heartbeat": "…/api/v1/desks/heartbeat", "me": "…/api/v1/desks/me", "leave": "…/api/v1/desks/leave",
               "records": "https://app.subello.com/mcp/records", "activity": "https://app.subello.com/mcp/activity",
               "memory": null, "actions": null,
               "models": {"url": "https://app.subello.com/desk-models", "models": ["claude-sonnet-5", "gpt-oss-120b"]}},
 "heartbeat_s": 300}
```

The token is shown once. `endpoints.models.url` is a base URL that serves
the OpenAI wire beneath it (`/v1/chat/completions`, `/v1/models`); `null`
means the office publishes no model endpoint to desks yet (the gateway
rung is then not made). `memory` and `actions` are `null` until the office
decides to publish them to desks (the kernel's D2 security decision).
Errors: 400 `invalid`, 403 `bad_code` (unknown, expired or used), 409
`name_taken`.

**Heartbeat request** (bearer)

```json
{"surface": 1, "presence": "online", "app_version": "maluos-desk 0.1.0", "mcp_surface_version": "1",
 "facts": {"hostname": "…", "os_release": "…", "cpu_cores": 8, "memory_mb": 15870, "storage_gb": 195}}
```

**Heartbeat and me answer** (200): `{"ok": true, "surface": 1, "desk": {id,
name, status, presence, last_seen_at}, "office": {…}, "owner": {…},
"endpoints": {…}, "heartbeat_s": 300}`. A retired desk answers 410
`retired`; an unknown or revoked token 401. The desk treats both as "no
longer enrolled here" and stops heartbeating until `leave` or a new
`enroll`.

**Leave** (bearer): 200 `{"ok": true}`; the desk is retired
(`status: retired`, `retired_at`) and the token revoked. 410 if already
retired.

## Files on the desk

| Path | Who writes it | Content |
|---|---|---|
| `/etc/maluos/office.yaml` (0644) | `maluctl office enroll` / `leave` | `surface`, `url`, `office`, `desk`, `owner` (member, login, principal), `endpoints`, `heartbeat_s`, `secret` (the vault name), `gateway` (what was added), `enrolled_at`. No token. |
| `/etc/maluos/office.env` (0644) | the same | `MALUOS_OFFICE_URL`, `_NAME`, `_DESK_ID`, `_DESK_NAME`, `_OWNER`, `_TOKEN_SECRET`, `_RECORDS_MCP`, `_ACTIVITY_MCP`, `_MEMORY_MCP`, `_ACTIONS_MCP`, `_MODELS_URL`; loaded by every `maluos-agent@` unit (`EnvironmentFile=-`) and by `maluctl agent run` |
| vault `user:<login>/office-desk-token` | the owner (through `enroll`) | the desk token; `use` by the gateway, `read` only by the owner or by grant |
| `~/.local/state/maluos/office.json` | `maluctl office heartbeat` | the last heartbeat's result (`ts`, `ok`, `presence`, `desk`, `error`, `revoked`) |
| gateway catalogue | `enroll` / `leave` | backend `office`, tier `office`, alias `office` → the first model the office listed |

## Commands

```
sudo maluctl office enroll URL --code CODE [--name N] [--owner LOGIN] [--no-gateway] [--force]
maluctl office status [--json] [--live]       the configuration and the last heartbeat; --live asks the office (as the owner)
maluctl office heartbeat [--presence online|offline] [--json]
sudo maluctl office leave [--keep-secret]
```

`enroll` and `leave` run with sudo from the owner's account (the sudo
user is the owner unless `--owner` says otherwise); the token is stored
and deleted *as the owner* (`runuser`), so the vault's peer identity holds
and the ledger names them. `heartbeat` runs as the owner: it reads the
token from the vault (`purpose: office heartbeat`), or takes it from
`MALUOS_OFFICE_TOKEN` in the environment, which is how the session service
avoids a vault read every five minutes: it reads the token once when it
starts heartbeating and again after a 401.

## The session

`maluos-desktop-session` 0.4.0 carries `office` in its state: `enrolled`,
`url`, `office.name`, `desk` (id, name), `owner`, `presence`,
`last_heartbeat_at`, `last_error`, `revoked`, `heartbeat_s`, `endpoints`
(which of records, activity, memory, actions, models the office
publishes), `gateway` (the rung's name when made). A heartbeat thread runs
`maluctl office heartbeat --json` every `heartbeat_s` while
`/etc/maluos/office.yaml` exists, with `presence: offline` when the service
stops (SIGTERM at logout). The indicator shows "Office: Subello · online"
with Open office and Check in now; the Desk's System page has an Office
group with the same. Notifications: the desk joined an office; the office
retired this desk. `OfficeAction(open|heartbeat)` on the bus.

## Decisions

- **A code, not a password.** The office mints a short-lived, single-use
  code for a person; the desk never sees a password and the office never
  sees the desk's. This is how a phone joins a wireless display and how
  Ubuntu Pro attaches a machine.
- **The token is the person's.** It sits in their vault compartment like
  their Anthropic key, with the same grants, delegations, ledger and
  requests. The gateway applies it for them; an agent gets it only by the
  owner's delegation (`use`) or grant (`read`). Nothing of the office is
  reachable from the desk without the person's say.
- **Presence is the session.** The desktop session is the signal that a
  person is at the desk; the heartbeat is theirs, as the owner, through
  the same token. A headless host is not a desk.
- **The gateway rung is the office's model endpoint, not a peer gateway.**
  The office's ledger proxy already is the "platform-hosted model
  endpoint" of the kernel's desk plan; the desk's gateway treats it as a
  cloud backend (`openai_compat`) with the desk token as the key, so the
  ladder, the sensitivity gate, the budgets and the local ledger all apply
  unchanged. Peer gateways (Phase 9, FR-21) are a different thing: a
  fleet's hosts sharing GPUs.
- **The kernel half was built after the owner approved it (2026-10-22).**
  In maludb-os-core: db/187 (`mcp_access_tokens.scope` gains `desk`, bound
  to the desk's location; `desk_enrollment_codes`; `locations.machine_id`),
  the four endpoints, the code from Settings → Desks or
  `bin/mint_desk_code.php`, the presence sweep, the allow-list lines; proof
  `bin/test_desk_enrolment.php`. A real office answers `endpoints.models`,
  `memory` and `actions` as null until their own kernel slice, so against
  it `enroll` makes no gateway rung yet; the mock office answers all of
  them and stays the boot test's office.

## MaluApps: the catalogue (Phase 12 slice 7)

`maluctl office apps` merges two lists, the office's over the public one,
and the MaluApps window shows the result. The office's list is
`GET endpoints.apps` with the desk token:

```json
{"ok": true, "surface": 1,
 "apps": [{"id": "helpdesk", "name": "Help Desk", "description": "Cases, queues and the Help Desk agent.",
           "icon": "help-faq", "kind": "web", "url": "https://app.example.com/apps/helpdesk", "version": "1"}]}
```

The public list is `https://download.maluos.com/apps/catalog.json`
(source: `docs/site/apps/catalog.json`, published with the download
page), the same schema with `path` (relative to the office's URL) in
place of `url` and `"requires": ["office"]` for apps that only exist on
an office. `kind` is `web` (installed as a launcher that opens the URL in
its own Firefox window), `deb` (`package`: installed from apt.maluos.com
through pkexec apt-get, `exec` to open) or `script` (not supported yet).
An entry from the office replaces a public entry with the same `id`. The
desk caches the merged catalogue per user for 15 minutes and shows it
stale when neither source answers. The mock office serves four web apps;
the kernel's `desks/apps` endpoint is specified here for the kernel
repository to build (the applications table decides what an office's
desks see). The public catalogue is served over HTTPS and not yet signed.

## Agents: the directory (Phase 12 slice 8)

`maluctl office agents` lists the office's agents this desk may use, from
`GET endpoints.agents` with the desk token, cached per user for 15
minutes; the session service reads it after each heartbeat and the
Agents app (maluos-agents) lists them beside the local agents:

```json
{"ok": true, "surface": 1,
 "agents": [{"id": "helpdesk", "name": "Help Desk agent", "description": "Triages cases and drafts answers.",
             "icon": "help-faq", "capabilities": ["helpdesk.triage", "kb.search"], "owner": "office", "node": "office-1",
             "presence": "online", "state": "idle",
             "page": "https://app.example.com/agents/helpdesk",
             "tasks": "https://app.example.com/api/v1/desks/agents/helpdesk/tasks",
             "activity": "https://app.example.com/api/v1/desks/agents/helpdesk/activity"}]}
```

`tasks` is the agent's task interface, the same JSON-RPC the local agents
serve on their sockets (`maluos_agent_tasks`: `agent/card`, `tasks/send`
with `message.parts[].text`, `tasks/get`, `tasks/list`), over HTTPS with
the desk token; `activity` answers `{"activity": [{"ts", "kind", "actor",
"summary"}]}`; `page` is the office's own page for the agent, which the
Agents app loads beside it. Any of the three may be absent. Start, stop
and restart of an office agent, and its logs, wait for the delegation
envelope of Phase 13 slice 2.

The Agents app requests `page` with the desk token as the Bearer header
on its first load (slice 9), so the office knows which desk and person
is looking; the office may answer with a session cookie that signs the
loads that follow in (the view keeps cookies for the window's life). A
page that ignores the header still works, with the office's own login.
The mock office answers "signed in as EMAIL at desk #ID" and sets
`office_session`. The mock office serves two agents; the
kernel's `desks/agents` endpoint is specified here for the kernel
repository (Agent HR decides what an office's desks see).
