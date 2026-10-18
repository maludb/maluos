# Build spec: Scheduled duties and delegation (stage H6)

> Plan: `docs/hermes-integration-plan.md` (H6). No new schema: `agent_duties` (db/042) already has
> `schedule_cron`, `timezone`, `last_run_at`, `next_run_at` and the due index; `agent_runs` has
> `trigger='duty'|'delegation'`, `duty_id`, `parent_run_id` (db/097); `agent_subagents` is the roster
> (db/072). The one action, `agent_delegate`, was approved at the H1 checkpoint and is in the manifest.
> Hermes' own `cronjob` and `delegation` toolsets stay **off**: the platform owns both, so every
> scheduled run and every delegated run is a row under a named member — never an anonymous child.

## Duties — the scheduler (`mcp/agent_runner/scheduler.py`)

A loop inside the runner, once a minute, when `RUNNER_SCHEDULER=on`:

1. a live duty with no `next_run_at` gets one (computed from its cron line and timezone) and is **not** run — a duty never fires the moment it is created;
2. a duty whose `next_run_at` has passed is started as a run (`trigger='duty'`, `duty_id`, the duty's `instructions`), then `last_run_at = now()` and `next_run_at` = the next time **after now**: a runner that was down for a day runs each missed duty once, not twenty-four times;
3. the agent is busy (one run at a time) → the duty stays due and is tried next minute; the run is refused for a standing reason (agent not active, no harness built for its model) → the duty moves to its next time and the reason is logged, so a broken duty cannot retry every minute forever.

`mcp/agent_runner/cron.py` is a small five-field cron evaluator (`*`, lists, ranges, steps, names
for months and weekdays, and cron's day-of-month OR day-of-week rule), evaluated in the duty's
timezone. No new dependency. A line it cannot parse parks the duty (`next_run_at` a year out) with
a logged reason rather than crashing the loop.

Budgets need nothing new: every duty run's model calls pass the ledger proxy, which refuses them
once the agent's monthly budget is spent.

## Delegation

`agent_delegate` — `html/agents/delegate.php` — **subagent**, **instructions**. Gate, all of it:
the caller is an **agent inside a run** (a run token), its `agent_kind` is `orchestrator`, the
subagent is on its live roster and active. It asks the runner for a run of the subagent with
`trigger='delegation'` and `parent_run_id` = the caller's run, and answers with the child's run id.
A busy subagent is a refusal the orchestrator reads, not a queue. Logs `agent_run.delegate`. One level
deep by construction: a subagent is not an orchestrator, so it can never pass the gate.

A one-shot run cannot wait for its child. So when a **family** is complete — the parent run has
ended, it delegated at least once, and every child has ended — the runner starts one
**continuation** run for the orchestrator (`trigger='delegation'`, `parent_run_id` = the parent),
briefed with each child's agent, status and result, and the original instructions. A continuation
may delegate again; the chain is capped at three continuations, and a family is continued once.

## Files

```
mcp/agent_runner/cron.py  scheduler.py  (+ service.py, store.py, config.py)   tests in tests/test_runner.py
html/agents/delegate.php   (+ app/features/agents/runs.php: find_roster_entry)
```

## Acceptance

1. A duty created through the agent form gets a `next_run_at` and does not fire at once; when due it
   runs with `trigger='duty'`, and `last_run_at` / `next_run_at` move on. A duty whose agent has no
   built harness is skipped to its next time with a reason, not retried each minute.
2. An orchestrator delegates to a rostered subagent: the child run carries `parent_run_id`; a
   subagent, a person, or an orchestrator naming someone off its roster is refused.
3. When the family completes, exactly one continuation run starts, briefed with the child's result.

## Built *(2026-09-19)* — acceptance as run on this server (scripted no-cost model)

| # | Result |
|---|---|
| 1 | A duty made through the agent form (`* * * * *`) had no `next_run_at`; the first tick logged *"first run at 20:04 UTC"* and ran nothing; the next tick started run 14 (`trigger='duty'`, `duty_id`), `last_run_at` set, `next_run_at` moved on. Removed through the form afterwards. With no harness built for an agent's model the duty is skipped to its next time with the reason logged. |
| 2 | Jack (orchestrator) delegated to Becky (on his roster) inside run 16 → run 17, `trigger='delegation'`, `parent_run_id=16`, running as Becky. Refused: a person; an agent's token outside a run; Jack naming Sasha — *"not on your roster. You can delegate to: Becky."* Becky, a subagent, is not offered the tool at all. |
| 3 | When run 17 ended the runner logged *"run 16: family complete; continuation run 18 started"* — once. The scripted model re-reads directives in the quoted instructions, so every continuation delegated again: 16→17, 18→19, 20→21, 22→23, and then *"delegation chain is 3 continuations deep; not continuing"*. The cap held. |

Found on the way: the manifest row's Params cell held an explanation with commas, and the registry
builder split it into nonsense parameters — the tool was generated without `instructions`. A Params
cell holds parameter names and short hints only.

The scheduler is **on** (`RUNNER_SCHEDULER=on` in `runner.env`). No duty exists; creating one is the
act that spends. 30 runner unit tests, including the cron evaluator's timezone, either-day and
never-fires cases.

## Open Questions

*(none)*
