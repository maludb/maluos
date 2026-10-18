# Build spec: AI Ops — "what did the models do, what did it cost, and is it still good?"

2026-09-20 · Module 12 of the stubbed modules (`docs/build-specs/stub-modules-decisions.md`,
owner's decisions 16 and 19). Schema: db/045 (prompt ledger + payloads), db/046 (evals), db/055
(`ai_usage_postings`, `eval_schedules`, `eval_alerts`), db/056 (the `ai_usage` posting rule,
Dr 6050 AI and model usage / Cr 2000 Accounts payable) + additive **db/116**. Manifest "AI:
prompt log, models & evals": 18 screens, 13 actions. Module keys: `ledger` (shown as "AI ops")
and `evals`.

## Already there (built by the agent-runtime work — verified, linked to, not rebuilt)
- Screens `models-settings`, `model-add`, `model-edit` and actions `model_save`,
  `model_set_status` (`html/settings/models/`, `/settings/models…`).
- The runner writes `agent_runs`, `prompt_ledger` and `prompt_payloads`; the agent page lists an
  agent's runs. Tools `agent_runs`, `ledger_calls`, `prompt_for_request` (`mcp/business_agents.py`).
- The `ai_usage` posting rule and accounts 6050 / 2000 (db/056); agent-approval policies for
  `ai_usage_posting.post` / `.void` (db/105).

## Who sees what — the views decide, nothing here widens them
- **Calls and runs** (`mcp_prompt_ledger`, `mcp_agent_runs`): the `ledger` grant; a person's own
  calls; an agent's calls for whoever may see that agent (its manager, its department's admin,
  HR). Any insider may open the screens — someone with none of those sees an empty list.
- **The prompt itself** (`mcp_prompt_payloads`) is the most sensitive read after pay: same
  people, humans only, plus an agent for its own calls. Shown as pretty-printed JSON in plain
  pre-wrapped text, never as HTML, capped at 400 KB per side on the page and absent from every
  list. A payload past `prompt_payload_retention_days` reads "payload expired" — the ledger row
  stays. **No prompt text is ever written to an activity payload.**
- **Evals** (`app_can_see_evals`): the `evals` grant or whoever may see the agent. **Cases are
  humans-only** (an agent that could read its cases could learn the test); every eval endpoint
  refuses an agent caller.
- **Postings** (`mcp_ai_usage_postings`): `ledger` or `expenses` grant, or super-admin.

## Evals: authoring is real, running is not (owner's decision 19)
Sets, cases (authored, or promoted from a real ledger call / run — the case keeps its source),
active / inactive, schedules. **There is no eval runner yet.** `eval_run_start` answers 409:
"Evals cannot run yet — the eval runner is not built. The set and its cases are saved." It
writes no run row and no score; a schedule is saved and listed and the screen says nothing
executes it; `next_run_at` stays NULL. `eval_result_grade`, `eval_alert_acknowledge` and
`eval_alert_resolve` are built (small, and correct for the day rows exist) though nothing can
produce a result or an alert today. Watch, graded traces and run pages render their honest
empty states. The eval gate on agent configuration changes (db/096) is untouched.

## AI usage reaches the books (owner's decision 16)
The prompt ledger is the AI subledger. `ai_usage_post` (**period** = `YYYY-MM`; super-admin or
the `expenses` grant; an agent pauses for approval with the amount) summarises that month's
ledger into `ai_usage_postings` rows — one per provider × model, status `posted` — and the
posting run carries each to the GL through the existing `ai_usage` rule, exactly as stock
movements and pay runs were added (`unposted_ai_usage()` in `app/features/books/posting.php`:
idempotent, period-aware, skipped with reasons). The journal entry is dated the period's last
day.
- **Closed months only.** A month is postable once it has ended; the current month is shown as
  "in progress — not yet" with its running total.
- Calls with no cost are counted but add nothing; a month whose cost is zero is refused
  ("nothing to post"). Only the business's base currency posts; other-currency calls are
  reported and left (no FX, by decision).
- Refuses if that period × provider × model is already posted. `ai_usage_void` (super; reason)
  marks the posting void and reverses its journal entry if it has one — after which the period
  can be posted again.
- **No expense row is created** (`expense_id` stays NULL): an expense would post a second time
  through the expense rule. The posting IS the expense, through account 6050. Recorded OPEN.
- Reconciliation = the posting's amount against the ledger's sum for the same period, provider
  and model today (late-arriving or re-priced calls show as a difference).

## db/116 (additive)
`journal_entry_id` appended to `mcp_ai_usage_postings` (last column; barrier and grants kept).

## Screens
`/ai/prompt-log` (agent, status, run, request, period), `/ai/prompt-log/{id}`, `/ai/runs/{id}`,
`/ai/spend` (period, group_by agent / model / provider / day / department), `/ai/spend/postings`,
`/ai/evals`, `/ai/evals/new`, `/ai/evals/{id}` (+ `/edit`), `/ai/evals/{id}/cases/new`
(`from_ledger`, `from_run`), `/ai/evals/cases/{id}/edit`, `/ai/evals/{id}/schedule`,
`/ai/evals/runs/{id}`, `/ai/evals/traces`, `/ai/evals/watch`, `/ai/evals/alerts/{id}`.

## Tools (new, `mcp/business_aiops.py`)
`ai_spend`, `model_catalog`, `eval_status`, `eval_findings`, `eval_watch`,
`ungated_deployments`. None returns a prompt payload; `eval_*` refuse agents where the surface
says humans only (`eval_watch` lets an agent see its own alerts).
