# Kernel chat endpoint — one turn of an application's agent (A6)

2026-09-22 · Business OS build plan, phase 7 Part A, step A6. Design: `docs/business-os-integration.md`,
"Agents — the application's command bar"; the application's side: the `maludb-os-integration`
plugin, `references/sign-on-and-directory.md` §5. Built the same day.

## What it is

An application's command bar posts what the person said; the kernel runs **one turn of the
application's shipped agent** — its expert, or another agent that holds access to it — as an
agent run with trigger `chat`: the agent's own grants, every model call through the ledger proxy,
approvals paused in the kernel's queue, the person as requester, the application stamped on the
run and on every ledger row it produced. The application never calls a model and holds no key.

| Piece | Where |
| --- | --- |
| `agent_runs.conversation_key`, `chat_utterance`; `mcp_agent_runs` appended; `GRANT UPDATE (application_id) ON prompt_ledger TO app_rw` | db/138 (with `application_id` on runs and the ledger from db/137) |
| `POST /api/v1/agents/chat.php?agent=expert|<id>`, `GET …?run=<id>` | `html/api/v1/agents/chat.php` — internal port; bearer = the application's token; `X-Acting-Member` = the person (`application_acting_member()` in `app/api/directory.php`) |
| The run | `start_agent_run(…, 'chat', …)` on the runner (no runner change); the kernel waits up to `wait` seconds (default 60, max 110), then answers 202 for a run still going |
| The prompt | who is asking, from which screen and context, the last three turns of the conversation (by `conversation_id`), then the person's words; capped at 8,000 characters |
| The answer | `run_id, request_id, status, finished, reply, error, approval_request_id, actions[{tool,status,duration_ms,record_id}], navigate (reserved), conversation_id, cost, currency` |
| Activity | `application.chat` with source `application`, the acting person as actor, the agent as entity, the run and request ids |

## Rules

- The agent is the application's expert (`applications.sme_agent_member_id`) or an agent with a
  live access grant on the application; it must be active; a busy agent is 409 (one run at a time).
- 400 no acting member · 403 no grant, or an agent without access · 404 no expert named · 409 busy
  or inactive · 422 an empty or over-long utterance, a bad `conversation_id`.
- `navigate` is always null: the kernel does not know an application's screens.

## Proven

Refusals before access (400, 404 no expert, 403 no access, 422 empty). Sasha granted access and
named expert of the test application, then a real turn as member 1: run 67 succeeded in 46 s on
Sonnet 5, reply in her words from `ai_spend`, three tool events reported, cost 0.0392 USD, the
four ledger rows stamped with the application, the run stamped with application and conversation.
A second turn with the same `conversation_id` carried the first into the prompt (run 68, 32 s,
0.0135). GET on the finished run answers 200. Both turns in the activity log with source
`application`. The test application was retired afterwards; the two runs are real work and stay.

## Open

- A turn holds the PHP request while the run goes; an application with many people should prefer
  a short `wait` and the GET. The runner allows one run per agent at a time, so a popular expert
  queues nobody — it refuses; a second expert per application, or a runner queue, is A7/A8 material.
- `record_id` on an action comes from the tool's event detail when the actions server puts it
  there; today the kernel's write tools answer `record_id` in their result, which the event does
  not carry.
