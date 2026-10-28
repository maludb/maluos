# Kernel — an application's credential at the ledger proxy (K24)

2026-10-05 · db/171. Owed by `/srv/apps/knowledge/docs/knowledge-design.md` §12 (owner's D4 and D15). Proof:
`mcp/agent_runner/tests/proof_application_credentials.py` (14 checks, on a scratch database).

## What it is

An application that makes model calls of its own through an engine behind it (Knowledge: MaluDB's extraction, embedding and
answers) sets the engine's provider API key to this credential and its provider URL to the ledger proxy. The proxy prices the
call, writes it to the prompt ledger stamped with the application (no agent, no run), forwards it with the real provider key
(held only in `runner.env`), and the call lands on the AI statement beside the agents' — the statement already groups by
application and tolerates a null agent (`app/features/aiops/statements.php`).

It is **not** the application token (`osapp_…`), which opens the directory, ledger-export and chat endpoints and must not travel
into a third service.

## Rules

| Rule | Where |
|---|---|
| One live credential per application; `appm_` + 48 hex, shown once, only the sha256 kept; minting again revokes the last | `application_model_credentials`, `bin/application_model_credential.php` |
| The proxy role holds no grant on the table: it resolves a presented key through `app_model_credential_resolve(hash)` (security definer; live credential, application `active` or `degraded`; stamps `last_used_at` at most once a minute) | db/171 |
| The caller names the model, but only among the credential's `allowed_model_ids` (active, `api_key` models; named by registry key or provider id). Any other model is refused 403 and nothing is forwarded. The upstream always receives the provider's own id. | `ledger_proxy._pick_model` |
| An optional monthly cap, money plus notional, counted over the application's own agentless calls (`application_model_month_cost`); at the cap the call is refused 402, nothing forwarded, and a `refused` row is written | `ledger_proxy._spent` |
| Routes: `/openai/v1/chat/completions`, `/anthropic/v1/messages`, `/openai/v1/models`, and **`/openai/v1/embeddings`**, which only an application credential may use (ledgered as `call_kind = 'embedding'`) | `ledger_proxy.py` |
| The ledger row: `application_id` set; `agent_member_id`, `agent_run_id` null; harness `application`; `acting_member_id` is the super-admin who minted it; prices from `model_registry`, so **every model must be registered with a price, an embedding model too** | `store.write_ledger` |
| Revoking, or retiring the application, shuts it at the next call (401) | proof |

## Using it

```
php bin/application_model_credential.php mint --app knowledge --models <registry keys> [--budget 50.00]
php bin/application_model_credential.php list
php bin/application_model_credential.php revoke --app knowledge
```

The engine's provider config then carries the printed key and a base URL of `http://127.0.0.1:8816/openai` (or `/anthropic`). A
button on the application's Overview, beside the application token, is owed (React); the CLI is the way until then.

## Going live

The migration is applied. The running runner holds the old proxy code: **`sudo systemctl restart maludb-os-agent-runner` (the
owner's) is what makes the credential work.** No agent run is affected by the change (the chat path is unchanged; the whole unit
suite, 41 tests, passes).

## Proven (scratch database `maludb_os_k24_scratch`, a login role holding only app_runner's privileges, a fake provider)

No key and an unknown key refused (401) · the model list is the allowed models · an embedding, a chat by provider id and a chat
by registry key forwarded, the upstream seeing the provider's model id and never the credential · a model outside the allowlist
403 · the cap stops the next call 402 with nothing forwarded · four ledger rows (embedding, two chats, one refusal) with no agent
or run, harness `application`, the minter acting, costs reconciled to the registry prices, every payload kept · the month's
spend 0.0142 · a retired application 401 · revoked 401 · the runner role cannot read the credentials table.
