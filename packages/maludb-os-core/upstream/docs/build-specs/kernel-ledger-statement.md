# Kernel ledger — the period statement and its exports (A5)

2026-09-22 · Business OS build plan, phase 7 Part A, step A5. Design: `docs/business-os-integration.md`,
"Token accounting". Built the same day.

## What it is

The kernel keeps token accounting only, with dollar costs, and exports it. Each calendar month the
prompt ledger rolls up into one **statement**: a line per provider × model × department (the
agent's primary) × agent × application × currency — calls, tokens by kind, amount. A month is
**open** (its statement is recomputed on demand) until a super-admin **closes** it, after which
its lines never change and a call that arrives for it later is a **late call**, folded into the
open month and flagged. Nothing here posts a journal; the accounting system is an application.

| Piece | Where |
| --- | --- |
| `ai_periods` (open/closed, the ledger high-water mark at close), `ai_usage_postings` as the statement (status open/closed/void, `closed_*`, `application_id`, `late_calls`, currency in the key), `application_id` on `prompt_ledger` and `agent_runs` (for A6) | db/137; views `mcp_ai_periods`, `mcp_ai_usage_postings` (recreated), `mcp_prompt_ledger` and `mcp_agent_runs` (appended) |
| Roll-up, close, the document, the CSV | `app/features/aiops/statements.php`: `rollup_ai_period()`, `close_ai_period()`, `ai_period_document()`, `ai_period_csv()`, presenters |
| Screen `ai-statements` | `/ai/spend/statements` → `html/ai/spend/statements.php`; the months, the chosen month's lines, Roll up / Close, CSV and JSON downloads |
| Actions | `ai_period_rollup` (`spend/rollup.php`, ledger grant), `ai_period_close` (`spend/close.php`, super-admin, past months only, confirmed) |
| The three exports | the file (`html/ai/spend/export.php?period=&format=csv|json` through the download route, logged `ai_period.export`); the feed for an application (`html/api/v1/ledger/periods.php?period=`, application token, internal port; no period = the months and their status); the MCP tool `ledger_period` on the records server |

## The document — `os.ledger-period/1`

`schema, business, period, period_start, period_end, status, closed_at, rolled_up_at, currencies[],
exchange, amount_scale, generated_at, lines[], totals[]`. A line: `provider, model, department,
agent, application, calls, late_calls, input_tokens, output_tokens, cache_read_tokens,
cache_write_tokens, amount, currency, note`. Totals are per currency; nothing is converted —
each line is in the currency the provider billed. The CSV is the same: a header pair, the lines,
one TOTAL row per currency. Amounts to four decimals.

## Late calls

Closing records `ledger_high_water`, the last ledger id at that moment. A ledger row dated in a
closed month with an id above that mark is late: the next roll-up of an open month counts it there,
`late_calls` says how many, the line's note says so. The closed month never changes.

## Proven

Roll-up of the running month (13 lines, 192 calls); closing the running month refused; closing a
past month; a call backdated into that closed month landing in the open month as one late call with
the note, and the closed month refusing a roll-up; the CSV with headers, lines and the TOTAL row;
the JSON document; the feed with an application token (months, one period) and 401 without; the
`ledger_period` tool for the months and for one month; every step in the activity log, the feed
with source `application`. The test rows were removed from the ledger afterwards.

## Open

- A6 writes `prompt_ledger.application_id` for chat runs; until then the application column is empty.
- Statement rows are keyed by the agent's primary department at roll-up time; a department change
  moves the agent's later statements, never a closed one.
