# The Accounting agents — what was set up, and what changed with the kernel

Hired 2026-09-19 by `golive.sh` (everything through the PHP handlers, as the owner): Accounting
first · $10 a month each · read, report and remember, every other write left to a person · one
weekday-morning duty each · **Sonnet 5** on the Hermes harness for all three.

**Re-versioned 2026-09-22 with the kernel cut** (`reversion.sh`, same pattern). The kernel keeps
token accounting only; Books, Expenses, Sales, Documents and Projects — everything the first
versions read and the tasks they created — are gone. Each agent got a new configuration version
with a job description about the ledger, and grants on the kernel's own tools.

| Agent | Job | Reads (Records MCP) | Actions | Duty (UTC, Mon–Fri) |
|---|---|---|---|---|
| Sasha (44) | Accounts Payable — model providers as vendors — `sasha.md` | ai_spend, model_catalog, ledger_calls | escalation_raise, memory_remember | 07:00 provider cost check |
| Becky (43) | Accountant — the ledger's period statements — `becky.md` | ai_spend, ledger_calls, agent_runs | escalation_raise, memory_remember | 07:30 ledger check |
| Jack (42) | CFO, orchestrator — `jack.md` | ai_spend, ledger_calls, agent_runs, agent_performance, approval_queue | agent_delegate, escalation_raise, memory_remember | 08:00 brief for the owner |

All three hold the three memory tools; Jack holds `agent_delegate` over a roster of Becky and
Sasha. Module access is read-only on `ledger` (the AI Ops grant). The handbook (`handbook.md`) is
the Accounting department's own handbook field, in every persona — edit it on the department's
page, not here.

## The first mornings (2026-09-19/20, before the kernel)

Kept for the record: run 24 (Sasha, Fable 5.1, 1.17) found duplicate bills and unapproved
expenses and wrote a skill; run 25 (Becky, Sonnet 5, 0.40) found unmatched bank lines; runs
26–28 (Jack → Becky → Jack, Sonnet 5, 0.58 in all) produced the first brief with four decisions.
The modules those runs read no longer exist here; the pattern — look, report, escalate, remember
— is what carries over.

**Spend to expect on Sonnet 5:** about 1.30 a morning for the team, ~28 a month, unevenly — a
delegated run is charged to whoever does it.
