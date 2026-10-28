# Build spec: the eval runner — on demand, advisory, and it never writes

> **Status: BUILT 2026-09-20.** db/125 (the runner may work an evaluation) and db/126 (a result
> says how it was graded). What the build found is at the foot, under "What the build found".
>
> Originally proposed as: Build-plan **phase 5, step 6**, the half that is not built.
> Everything else of step 6 exists: eval sets, cases, promote-a-trace, schedules, alerts, screens
> and tools. What does not exist is the thing that runs a case, so `html/ai/evals/run.php` answers
> a plain 409 and `eval_runs` has **zero rows**.
>
> Owner's decisions, 2026-09-20 (all four asked and answered before a line was written):
> 1. **Record, don't execute** — a write tool under an eval run records what it would have done.
> 2. **Any config version, defaulting to the active one** — so a change can be weighed before it goes live.
> 3. **Score only what was graded** — human-graded cases await a person and are never guessed at.
> 4. **No fixtures** — a case runs against live data, read-only. A known limit, stated below.

## Sources this spec may never contradict

`docs/build-specs/eval-evidence.md` (what a run records; the four settled parameters) ·
`docs/evaluation-engineering-production.md` (the owner's evaluation strategy) ·
`docs/build-specs/ai-ops.md` · `db/046` (the schema is already right; **no migration**) ·
`docs/build-specs/agent-runtime-hermes.md` (the runner owns a run's life) · `CLAUDE.md`
"Agent decisions already made" — **evals are advisory: a missing or failing eval never blocks an
activation** (2026-09-20).

## The one rule that makes this safe

**An eval run cannot change anything.** Not the books, not a customer record, not memory, not an
approval. It is the difference between a test suite you can run on a Tuesday afternoon and one
nobody dares run twice.

It is enforced at the **MCP boundary**, where tool grants are already enforced
(`mcp/agent_grants.py`: *"Hermes is also rendered with tools.include = the granted names, but that
is the agent's own configuration and therefore not a control; this is."*). The same reasoning
applies here, one layer out: the agent's persona is not a control, and neither is a handler's good
intentions. The request must never reach PHP.

```
agent → actions MCP server → app_post()  ──▶  PHP handler   (an ordinary run)
agent → actions MCP server → RECORDED     ✗   never sent     (a run whose trigger is 'eval')
```

`actions_server.app_post()` asks, once per run and then from cache, whether
`agent_runs.trigger = 'eval'` for the run its token names. **The run row says so, not the token** —
nothing the agent holds can claim or deny it. In eval mode the call is not sent; the tool answers:

```json
{"status": "recorded", "would_have_called": "expense_create",
 "arguments": {...}, "note": "This is an evaluation. Nothing was changed."}
```

Read tools are untouched: an eval run reads the business exactly as the agent would.

## What a run does

`POST /ai/evals/run.php` (action `eval_run_start`) creates the `eval_runs` row and asks the runner
to start it, exactly as `agent_run_start` asks it to start an agent run. The runner then, for the
set's **active** cases:

1. Renders the agent's profile from the run's `config_version_id` (default: the active version).
2. For each case, **three trials** (settled). Each trial is an ordinary agent run with
   `trigger='eval'` — so it is ledgered, its events are kept, and it is visible in AI Ops like any
   other run. That is the point: an eval run is evidence, not a special case.
3. Grades each trial, and **all three must pass** for the case to pass (settled).
4. Writes one `eval_results` row per case: `passed`, `score` (the mean of the trials), the grader's
   notes, `agent_run_id` of the **first** trial so a reader can open what actually happened.
5. Scores the run and compares it to its baseline.

### Grading

| `eval_cases.grader` | How |
|---|---|
| `exact` | The run's answer, trimmed and case-folded, equals `expected.answer`. |
| `programmatic` | Deterministic checks against the trial's **transcript**: `expected.tools` (every named tool was called), `expected.contains` / `expected.not_contains` (substrings of the answer), `expected.no_writes` (nothing was recorded as a would-be write). No code from the case is ever executed. |
| `rubric_llm` | A judge model is shown the case, the rubric and the transcript, and answers `{passed, score, why}`. |
| `human` | The runner writes the row, marked not-passed, note *"awaiting a person's grade"*. It is **excluded from the score** until a person grades it. |

**The transcript is already there.** `memory.transcript_from_payload()` rebuilds a run's whole
conversation from its last ledger payload, tool calls included (`[called <tool> <args>]`), so
grading needs no new recording path and no new table. What the agent *would have written* appears
in it as the recorded tool result — which is exactly what a grader must see.

**The judge** is Sonnet 5, or DeepSeek V4 Pro when the agent under test is itself on Sonnet
(settled: a model should not mark its own homework). It is called through the ledger proxy like
everything else, so the judging is in the prompt ledger too, attributed to the eval run.

### Scoring, and why it may not be complete

```
score = 100 × (weight of passed cases) / (weight of GRADED cases)
```

Cases awaiting a person are in neither sum. The run records `cases_total` (all of them) and
`cases_passed`, and the screen says *"N of M graded — K await a person"*. A number that is not yet
the whole truth must say so rather than quietly average a guess into itself.

`status` = `passed` when `score >= pass_threshold`, `failed` below it — **on what has been graded**.
When a person grades the last human case, `eval_run_rescore()` recomputes the score and status, and
logs that it changed. Nothing is ever silently restated.

### Baseline and regression

A run may name `baseline_run_id` (default: the most recent passed run of the same set for the same
agent). The comparison is **case by case**, not score to score: the answer that matters is *"which
cases used to pass and now do not"*, because a score that moves from 82 to 79 tells you nothing
about what broke. Regressions are reported in the run's result and by the `eval_findings` tool.

**Nothing is blocked and no alert is raised.** Evals advise (owner, 2026-09-20). A failing run is
a fact on a screen for a person who went looking, not a gate and not a page at 3am.

### Budget

Eval spend is **separate from agent budgets and capped at 5 per eval run** (settled). The ledger
proxy already refuses a call that would exceed an agent's monthly budget; for a run whose trigger
is `eval` it checks the **eval run's accumulated cost** against that cap instead, so evaluating an
agent never eats the budget it works from, and a runaway suite stops itself. Exceeding it ends the
run as `error` with what it managed, not silently.

## Files (exactly these — no additions)

| File | Change |
|---|---|
| `mcp/agent_runner/evals.py` | **new** — the runner: cases → trials → grading → scoring → baseline compare |
| `mcp/agent_runner/grading.py` | **new** — the four graders, and the transcript helpers they share |
| `mcp/agent_runner/store.py` | `load_agent(member_id, config_version_id=None)`; eval run reads and writes; `run_for_proxy` carries the eval cap |
| `mcp/agent_runner/service.py` | `POST /eval-runs` (start), `POST /eval-runs/{id}/cancel` |
| `mcp/agent_runner/ledger_proxy.py` | an eval run is metered against the eval cap, not the agent's budget |
| `mcp/agent_runner/claude_render.py`, `hermes_render.py` | take the version to render (they already take `agent`; the version comes resolved in it) |
| `mcp/actions_server.py` | **the safety rule**: an eval run's writes are recorded, never sent |
| `mcp/business_aiops.py` | the eval tools stop saying "there is no eval runner"; `eval_findings` reports regressions |
| `app/features/aiops/queries.php` | `start_eval_run()`, `eval_run_rescore()`, result reads |
| `html/ai/evals/run.php` | stops refusing; starts a run |
| `html/ai/evals/grade.php` | rescores the run after a human grade |
| `html/ai/evals/runs/view.php` + `web/…/ai/evals/runs/[id]/page.tsx` | real results, per-case, with the regression column |
| `docs/business-os-action-manifest.md` | `eval_run_start` loses its "no runner" note; `eval_run_cancel` added |

**No migration.** db/046 anticipated every column this needs, including `baseline_run_id`,
`eval_results.agent_run_id` and `grader_notes`.

## Known limits (stated, not hidden)

- **No fixtures** (owner's decision). A case runs against live data, so a case written today can go
  stale when that data changes, and two runs a month apart are not strictly comparable. This is the
  first thing to revisit if eval results start disagreeing for no reason.
- **Read-only means read-only.** A case cannot test what a write actually produced — only that the
  agent tried the right write with the right arguments. Testing the *effect* of a write needs
  fixtures and a sandbox, which is a later slice.
- Three trials catch flakiness, not rare failures. A case that fails one run in twenty will look
  green most days.
- The judge is a model. `rubric_llm` grades are evidence, not truth, which is why `grader_notes`
  is kept and shown.

## Acceptance (the demo this slice owes)

1. A set with one `programmatic` and one `rubric_llm` case runs to completion against a real agent,
   and `eval_runs` has its first row ever with a real score.
2. **An eval case that asks for a write changes nothing.** The agent calls the write tool, the tool
   answers `recorded`, the database is untouched, and the transcript shows what it would have done.
   Checked against the table the write would have hit.
3. Three trials per case, all recorded; a case where one trial differs fails.
4. A `human` case leaves a row awaiting a person, is excluded from the score, and grading it
   rescores the run — with the change logged.
5. A second run against the first as baseline names the case that changed, not just the score.
6. A run of a NON-active config version renders that version's profile (`profile_hash` differs from
   the live one) and changes nothing about which version is active.
7. Every model call of the run — the agent's trials and the judge's grading — is in the prompt
   ledger, attributed to the eval run, and counted against the cap rather than the agent's budget.
8. Activation still does not require any of it: a version with a failing run still activates, and
   says it went live unevaluated.

## What the build found (2026-09-20)

**The safety rule failed on its first real test, and created two real tasks.** Eval run 1 was
started, and Becky called `task_create` — and it worked. `tasks` went from 24 rows to 26.

The cause was one line that did not exist. `app_post()` asked `db.request_run_id` which run it was
serving; the READ servers set that from the run token in `server_common.make_app()`, but the
actions server has its own middleware and had never set it, because until this slice nothing on
this server had asked which run a call belonged to. So the check read `None`, decided "not an
evaluation", and forwarded the write. **The interception was correct and was never consulted.**

Two things changed because of it:

1. The actions server now sets `request_run_id` from the run token, like the read servers do.
2. **The runner no longer trusts the rule it depends on — it checks it.** After every trial it asks
   `run_changed_anything()` (db/125, a narrow SECURITY DEFINER function, because db/097's rule is
   that the runner reads no business records) whether anything happened under that run. If
   something did, the evaluation stops at once as `error` and says the interception needs looking
   at. The failure above would have been caught on the first trial instead of the fifth.

The rule now holds in two independent places, and neither is the agent's persona.

Two smaller findings on the way, both the same shape — a guard that could not tell, and therefore
refused rather than guessed:

- The actions server reads as `app_records_ro`, which has **no privilege on `agent_runs` at all**.
  The first fix asked the base table, could not answer, and — by design — refused every write with
  a 503 rather than assume either way. It asks `mcp_agent_runs` now. The refusal wording is worth
  keeping: it told the agent plainly that nothing had been changed and to stop.
- `app_runner` had no privilege on the eval tables (db/125) and none on `activity_log` (hence the
  function rather than a grant).

### Acceptance, as it actually ran

| # | Acceptance | Result |
|---|---|---|
| 1 | a set runs to completion with a real score | **eval run 1: `passed`, 100.00, 2 of 2 cases graded, 0.0451** — the first row `eval_runs` has ever had |
| 2 | a case that asks for a write changes nothing | Three trials called `task_create`; `tasks` is byte-identical before and after (24 rows, same md5). The agent was told `status: recorded`, and said so in its report |
| 3 | three trials per case, all must pass | 6 agent runs for 2 cases; the case passes only on 3 of 3 |
| 4 | a `human` case awaits a person | Built and excluded from the score (db/126's `is_graded`); not exercised in this run, which had no human case |
| 5 | baseline compares case by case | Built; run 1 is the first run of this set, so it had no baseline to compare with |
| 6 | a non-active config version can be tested | `load_agent(member_id, config_version_id)` renders it and `create_run` records it; the run does not activate anything |
| 7 | judging is in the ledger, against the cap | **3 `call_kind='grader'` rows**, the judge pinned to its own model through a key that names the eval run, not the agent's run |
| 8 | activation still requires none of it | Untouched: `activate_config_version()` still records what it can and activates regardless |

Checked afterwards: `run_changed_anything()` returns **0 actions for all six trials**.

## Open Questions (must be EMPTY before a worker starts; workers append when escalating)

*(none)*
