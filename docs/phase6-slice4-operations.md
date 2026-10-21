# Phase 6, slice 4: degradation, alerts, delegation, export

Delivered 2026-10-18 in maluos-vault 0.2.0 and maluos-gateway 0.3.0. It
completes the requirements of docs/phase6-inference-gateway.md that the
earlier slices left open: FR-15 (delegation), the export and import of
FR-18, FR-32's cool-downs, FR-42 (an episode per call with a task
reference), FR-44 (alerts), FR-45 to FR-48 (degradation) and the restart
accounting of FR-47.

## Delegation (FR-15)

A user may let an agent use their keys without ever reading them:

```
maluctl secret delegate --to agent:research --secret anthropic --expires 7d --budget usd_per_day=2
maluctl secret delegations
maluctl secret undelegate --to agent:research --secret anthropic
```

The vault grants the agent `use` (never `read`) on the named secret, or on
all of the user's secrets when none is named, until the expiry; every use
is logged with the reason `delegation:<user>` and the gateway's broker
row. Operators may delegate on a user's behalf (`--from`). The budget is
recorded for the ledger; enforcement against it is per-principal through
the gateway's policy budgets for now.

## Episodes (FR-42)

A model call that carries a task reference (`X-MaluOS-Task` or
`maluos.task` in the body) writes an episode of kind `maluos.model_call`
into the tenant's memory, with the principal, route, tokens and cost in
its payload, and links it from the ledger row (`episode_id`). The daemons
hold no memory privilege: the tenant owns a definer function,
`maluos_record_episode`, that records episodes of the daemons' kinds and
nothing else.

## Alerts (FR-44)

| Alert | When |
|---|---|
| `budget` | a principal passes `warn_at` (default 80 %) of a period budget |
| `budget_exceeded` | a call is rejected for budget |
| `backend_down` | a backend has been unhealthy for `alerts.backend_down_s` (300 s), repeated hourly |
| `backend_recovered` | it answers again |
| `usage_anomaly` | a principal made more than `factor` (3) times its 7-day hourly average in the last hour, and at least `min_calls` (20) |
| `restart_lost_work` | the gateway restarted with engine requests in flight |
| `retired_key` | a rotated secret's previous value was presented within its grace window |

Every alert goes to the journal, to the ledger (`alert.<kind>`), to the
tenant's memory as an episode of kind `maluos.alert`, and to hooks: every
executable in /etc/maluos/alert-hooks.d receives the alert as JSON on
stdin (a mail or chat relay is a ten-line script there). `maluctl gateway
alerts` and `maluctl secret alerts` list them; operators can raise one by
hand with `POST /v1/maluos/alert` for monitors that watch something else.

## Degradation (FR-45 to FR-48)

- GPU or local Ollama down: cloud-allowed requests continue down the
  ladder; local-only requests fail with `local_unavailable` and the
  expected reasons on the ledger row.
- Network down: cloud backends fall into a 60 s cool-down after a
  connection failure and are skipped; cloud-only work fails fast with
  `cloud_unreachable`; local work is unaffected.
- Vault down: cloud rungs are skipped with `vault_unavailable`; local
  routes need no credential and continue.
- Gateway restart: the gateway keeps the engine requests it has claimed in
  /var/lib/maluos-gateway/engine-inflight.json; on start it fails any that
  are still `running` as `gateway_restart`, writes a `gateway.restart`
  ledger row listing them, and raises `restart_lost_work`. HTTP callers
  lose their in-flight calls as before (the socket is socket-activated,
  so new calls queue during the restart).

## Export and import (FR-18)

```
sudo maluctl secret export /root/vault-2026-10-18.bin          # passphrase prompt; --passphrase-file F for scripts
sudo maluctl secret import /root/vault-2026-10-18.bin
```

The bundle holds compartments, secrets with values, grants and
delegations, encrypted with AES-256-GCM under a key derived from the
passphrase with scrypt. Every exported value is a logged read (`purpose:
export`), the export and import are ledger events, and import upserts
(existing secrets are rotated to the imported value). This is the way to
move a vault between machines when the master key is sealed to a TPM, and
the backup to take before replacing hardware.

## Tests

The gateway harness grew to 119 checks: delegation used by an agent (the
user's key, use only, revocation), episodes for task-bearing calls, the
budget alert on all three channels (ledger, episode, hook), manual alerts,
backend down and recovered alerts with the mock stopped and restarted,
`local_unavailable` and `cloud_unreachable`, restart accounting with a
long engine request lost across a gateway restart, the usage anomaly after
a burst, export (encrypted, logged, operators only) and import (restores a
deleted secret; wrong passphrase refused), and the retired-key alert.

## Later: grant requests (Phase 12 slice 3, maluos-vault 0.3.0)

A refusal now files a pending request for the secret's owner
(`maluos_secret_request`; one pending per secret and requester, asking
again bumps it; a refusal within a day of a denial does not re-file).
`GET /v1/requests`, `POST /v1/secrets/REF/request`,
`POST /v1/requests/ID/approve|deny`; `maluctl secret requests | request |
approve | deny`. The error body of a refusal carries `request_id`. The
registry `maluos_agent` (written by maluctl agent) lets the ledger scoping
show a person the rows of the agents they own. See docs/phase12-desktop.md.
