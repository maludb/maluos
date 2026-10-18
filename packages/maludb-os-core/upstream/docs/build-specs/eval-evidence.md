# Build spec: the evidence evaluations will need (owner's direction, 2026-09-20)

> Design input: `docs/evaluation-engineering-production.md` (the owner's evaluation strategy), Step 5
> "Instrument runs and traces", and principles 6 and 12 (log what reproduces a result; preserve
> evidence, not just scores). **Evals themselves are on demand and advisory** — a person runs them when
> weighing a model or prompt change or looking into a degradation; a missing eval never blocks an
> activation. What cannot wait is the data: it cannot be backfilled.

## Audit — what a run records (checked 2026-09-20)

| An evaluation needs | Where it is | State |
|---|---|---|
| Prompt, full context, model settings, tool definitions as granted at that moment | `prompt_payloads.context` per model call | ✅ 100% of calls, nothing prunes them |
| Response, stop reason, the model that served it | `prompt_payloads.response` | ✅ |
| Tokens ×4, latency, cost, status, provider request id | `prompt_ledger` | ✅ |
| Persona, handbook, core memory, recalled memory | inside the context (system prompt / first message) | ✅ |
| Config version, model, harness + SDK version, profile hash, skill names + hashes | `agent_runs` | ✅ |
| Trigger, duty, who asked, parent run, instructions, result, error, timings | `agent_runs` | ✅ |
| Every action taken, the record, approvals it waited on | `activity_log` (`agent_run_id`, `request_id`), `approval_requests` | ✅ (`agent_timeline` reads it) |
| Tool arguments and results | the NEXT call's context | ✅ |
| **Which tool ran, whether it failed, how long it took** | runner memory only — lost at restart | ❌ → **fixed: `agent_run_events` (db/122)** |
| **The command-bar assistant's calls** — the most-used AI in the product | nowhere | ❌ → **fixed: `mcp/ledger_writer.py`** |
| The last events of a run (final tool result, session end) | dropped when Hermes exited first | ❌ → **fixed: the observer drains at exit** |
| A person's verdict on a run ("good" / "wrong", with a note) | nowhere | ❌ → **fixed: `run_verdicts` (db/124)** |

## Built

- **db/122 `agent_run_events`** — one row per event the harness's observer reports, in arrival order:
  event, tool name, tool call id, status, duration, error type/message, API request id, a small `detail`.
  No arguments or results (they are in `prompt_payloads`), so it stays small enough to keep for good.
  The runner writes each event as it arrives (`service._record` → `store.add_event`); a failure to keep one
  is logged and never breaks a run. `mcp_agent_run_events` shows them to whoever may see the run.
- **`mcp/bos_hermes` observer** drains its queue at interpreter exit (3 s at most). Reinstalled into
  `/opt/hermes/venv`. Proven: run 31 kept 14 events, `on_session_end` included.
- **`mcp/ledger_writer.py`** — prompt-ledger rows for model calls made outside the runner, written as
  `app_rw`. The assistant records every `messages.create`: the person as `acting_member_id`, harness
  `native`, one `request_id` per turn, the whole request (system, tools, messages) plus the surface the
  person was on (screen, entity, record), the response, usage, latency, cost from the registry's prices.
  Errors are recorded too. A ledger failure is logged and never breaks the person's turn.

## Found by turning the light on

The first ledgered assistant turn cost **1.03** for a one-sentence answer: **~255,000 input tokens per
call** — 469 tool definitions, 660,000 characters, sent whole on every call with no caching. Fixed the
same hour with two cache breakpoints (after the last tool, after the system prompt) and a stable tool
order: the first call of a five-minute window writes the cache (0.64), every later call reads it
(**0.05**, and 3 s instead of 11 s). **Still open:** the right fix is tool search — load a tool's
definition only when it is needed — which is a change to the command bar's design (`chat-actions`).

## Activation no longer refuses

`activate_config_version()` records a passing eval run for the version when one exists and otherwise
activates all the same, saying — on the screen, in the HR event, in the log — that the version went live
unevaluated. No database trigger enforced the old gate. Requirements (three copies), build plan (two
copies), `CLAUDE.md` and `docs/build-specs/agent-hr.md` say the same.

## Open — for the owner

1. ~~**A person's verdict on a run.**~~ **BUILT 2026-09-20** (owner approved it the same day).
   `db/124 run_verdicts` — good or bad plus a note, on an agent run or on one assistant answer; one
   verdict per person per subject, and saying it again changes it. An agent may never give one: the
   handler refuses an agent caller and a trigger refuses the row, because marking your own homework
   is not evidence. Action `run_verdict_set` (`html/ai/verdict.php`), the card on both `/ai/runs/{id}`
   and `/ai/prompt-log/{id}`, and the `run_verdicts` MCP tool — whose answer says plainly that no
   verdict is the commonest case, so silence is never read as approval.
2. **Tool search for the assistant** (above).
3. ~~**Side effects in eval runs**~~ — **decided 2026-09-20: record, don't execute.** Under an eval run
   token a write tool records what it WOULD have called and returns without writing, and the case is
   graded against that. Nothing an eval run does can touch the books, the ledger or a customer record.
4. Settled for that runner: three trials per case, all must pass; judge = Sonnet 5, or DeepSeek V4 Pro when
   the agent is itself on Sonnet; eval spend separate from agent budgets, capped at 5 per eval run.
