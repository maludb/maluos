# Desk enrolment — a MaluOS desktop joins the estate (stage D2, the kernel half)

2026-10-22 · Business OS build plan, phase 6 "Desktop beta", item 2, and `docs/desktop-agent-plan.md`
stage D2. **Approved by the owner 2026-10-22 and built the same day** (db/187, `app/features/estate/desks.php`,
`html/api/v1/desks/`, `html/settings/desks/code.php` + the Desks section of Settings, `bin/mint_desk_code.php`,
`bin/cron/desk_presence.php`; proof `php bin/test_desk_enrolment.php`, 39 checks on the internal port — `BOS_INTERNAL_URL` names it when it is not :8080). The desk half is built in MaluOS
(`maluos-desk`, `maluctl office`; contract `docs/desk-enrolment.md` there) and proven against a mock
office that implements this spec.

## What it is

A desk is a `locations` row of kind `desk` (db/043): it has an owner, `enrollment_token_id`,
`enrolled_at`, `presence`, `last_seen_at`, the facts the companion reports about itself (`hostname`,
`os_platform`, `app_version`, `mcp_surface_version`, `cpu_cores`, `memory_mb`, `storage_gb`). Today
those are "phase 6, screen only". This slice gives them their writer: four endpoints under
`/api/v1/desks/` on the person face, a **desk token** (an `mcp_access_tokens` row of a new scope
`desk`), and a one-time **enrolment code** a person mints for themselves.

The desk acts as the person: the desk token reads what the person's own `mcp` token reads
(records, activity), and calls the model endpoint as the person, ledgered with `surface = desk`
(the plan's D2). Nothing new is granted; a desk never widens its owner's reach.

## Schema (one migration, additive)

```sql
-- db/187_desk_enrolment.sql   (db/185 is reserved for the forge's K61, db/186 is K65)
ALTER TABLE mcp_access_tokens DROP CONSTRAINT mcp_access_tokens_scope_check;
ALTER TABLE mcp_access_tokens ADD CONSTRAINT mcp_access_tokens_scope_check
    CHECK (scope IN ('mcp', 'api', 'application', 'desk'));
ALTER TABLE mcp_access_tokens ADD COLUMN location_id bigint REFERENCES locations(id) ON DELETE SET NULL;
CREATE UNIQUE INDEX mcp_access_tokens_desk_live_idx ON mcp_access_tokens (location_id)
    WHERE scope = 'desk' AND revoked_at IS NULL;

CREATE TABLE desk_enrollment_codes (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id     bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,   -- who the desk will belong to
    code_hash     text NOT NULL UNIQUE,                                        -- sha256 of the shown-once code
    desk_name     text,                                                        -- optional, chosen when minting
    expires_at    timestamptz NOT NULL,                                        -- 15 minutes
    used_at       timestamptz,
    location_id   bigint REFERENCES locations(id) ON DELETE SET NULL,          -- the desk it made
    created_by    bigint NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX desk_enrollment_codes_member_idx ON desk_enrollment_codes (member_id) WHERE used_at IS NULL;

ALTER TABLE locations ADD COLUMN machine_id text;      -- the desk's sha256(machine-id) prefix: re-enrolment of the same machine
COMMENT ON COLUMN locations.machine_id IS 'desk: what the companion reports as its machine identity (hashed); a re-enrolment with the same value retires the old row.';
```

`mcp_locations` (db/069) gains `machine_id` appended last. The activity log records `desk.enroll`,
`desk.heartbeat` is **not** logged (every five minutes; activity memory cannot be un-polluted —
`last_seen_at` is the record), `desk.leave`, `desk.retire`, `desk.code.mint`.

## Endpoints (`html/api/v1/desks/`, person face, on the public allow-list)

| Endpoint | Auth | Does |
|---|---|---|
| `POST enroll.php` | the code | finds a live, unexpired, unused code; makes the desk (`kind desk`, `owner_member_id` = the code's member, `parent_location_id` = the office the owner's primary department sits at, `is_always_on false`, the facts, `external_ref` = the desk principal, `enrolled_at now()`, `presence online`); mints the token (`scope desk`, `location_id`, label "Desk: <name>"); marks the code used; 201 with the answer below |
| `POST heartbeat.php` | bearer desk | `presence`, `last_seen_at`, the facts; 200 with the desk, owner and endpoints; 410 `retired` when the row is retired; 401 otherwise |
| `GET me.php` | bearer desk | the same answer, no write |
| `POST leave.php` | bearer desk | `location_retire` semantics: `status retired`, `retired_at`, the token revoked; 200 |

The answer shape (`surface: 1`) is in MaluOS `docs/desk-enrolment.md`: `desk {id, name, status,
presence, last_seen_at}`, `office {name: business_name(), url: app_url('/')}`, `owner {member_id,
email, display_name}`, `token` (enroll only), `endpoints {heartbeat, me, leave, records, activity,
memory: null, actions: null, models: null | {url, models[]}}`, `heartbeat_s: 300`.

`endpoints.memory`, `actions` and `models` stay `null` in this slice: publishing the memory and
actions MCP servers and the ledger proxy's model routes to desks is the plan's own D2 security
decision (short-lived desk-session keys, rate limits, `surface = desk` on the ledger row) and is
specified separately once this half is approved. The desk side already treats `null` as "not
published" and makes no gateway rung.

The four endpoints authenticate with `desk_authenticate()` (`app/features/estate/desks.php`), which
accepts `scope = 'desk'` only; `api_authenticate()` keeps `scope = 'api'`, so an `api` or `mcp` token is
refused on `/api/v1/desks/*` and a desk token on `/api/v1/me`: one revocation never means two surfaces
(db/078's rule). The records and activity MCP servers resolve bearer tokens through `mcp_resolve_token()`,
which takes any live token regardless of scope (db/014) — a desk token reads there as its owner with no
change. **As built:** the desk token is also accepted by `/mcp/*` for an `api` token's reasons; the
per-surface refusal on the MCP servers is a later tightening that would touch personal and application
tokens too.

## The code

`POST /api/v1/desks/codes` is **not** an endpoint: minting is a screen (`/settings?section=desks` →
"Enrol a desk", the person's own; `html/settings/desks/code.php` answers the code once, through
`settingsSecret()` like a new token) and a CLI for operators, `php bin/mint_desk_code.php --email
ed@example.com [--name "Ed's desk"]`. The Desks section lists the person's live desks with presence and
a Retire button (`locations/retire.php`, the owner's own action). Eight characters from an unambiguous alphabet, shown once
with its expiry; one live code per person at a time (minting again replaces it). A used or expired
code is `403 bad_code`; the message never says which.

## Presence

The scheduled presence job (estate spec, "written by the scheduled presence job") sets a desk to
`offline` when `last_seen_at` is older than `3 × heartbeat_s`. A desk says `offline` itself when its
session ends; the job is for desks that lost power.

## Apache

`docs/deploy/apache-react-cutover.conf`: `/api/v1/desks/` joins the allow-list
(`^/(?!mcp/|api/v1/desks/)` → the React app), beside `/api/v1/{health,me,members,org-graph}`.

## Acceptance

- A person mints a code in Settings; `sudo maluctl office enroll https://app.<domain> --code …` on a
  MaluOS desktop makes a desk under their name in Work Locations, online, with the right facts; the
  code cannot be used twice.
- The desk's records and activity reads with the desk token appear in the activity log as the
  person, `source desk`.
- Stopping the desktop session sets the desk offline within a minute; a desk retired from Work
  Locations answers 410 and the desk's session says so.
- `maluctl office leave` retires the desk and revokes the token; a later heartbeat with the old
  token is 401.
- A desk token presented to `/api/v1/me` or `/mcp/actions` is refused.

## Deploy

`db/187` as postgres; `docs/deploy/apache-react-cutover.conf` (the two `desks` rewrite lines) and a reload;
`docs/deploy/crontab.example` (the presence job); `npm run build` for the Desks section. A MaluOS office
picks all of it up when the kernel package is re-vendored at this commit.

## Not in this slice

The model endpoint for desks and `surface = desk` on the prompt ledger (plan D2's second half),
the Hermes profile endpoint (D4), `ui_*` (D3), the desk's resident agents as members.
