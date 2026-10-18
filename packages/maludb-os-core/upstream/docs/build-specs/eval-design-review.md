# The evaluation design, checked against the five Claude Architect modules (2026-09-20)

> Read in full, line-referenced: `docs/Eval-Module-1.md` … `Eval-Module-5.md` (Claude Certified Architect
> — Professional preparation). Checked against: the owner's strategy (`docs/evaluation-engineering-production.md`),
> the evidence spec (`docs/build-specs/eval-evidence.md`) and the owner's decisions — evals **on demand**,
> **advisory**, goals set before a run. M1:30 = Module 1, line 30. Three claims the reviewers made were
> wrong and are dropped: that `CLAUDE.md` still said evals gate and run continuously (it did not — though
> its Audit line did, fixed with this file); that no route exists from a real run to a case (`/ai/evals`
> has promote-from-trace); that delegated runs share no trace (`agent_runs.parent_run_id` links them).

## Where the modules argue against a decision the owner has made

Stated plainly, because they do.

1. **"A missing eval never blocks activation."** The modules treat a model or prompt change as a release and
   the eval as its gate: *"use evaluations as the gate before any model swap"* (M1:30), *"a delta threshold…
   below which you do not ship"* (M1:1058-1064), *"No eval set means no rollback signal"* (M1:1087), every
   change *"should run through the eval suite… before it moves to production. This is the only reliable
   way"* (M2:108), and M5:139: *"Wherever a check can be made automatic, it should be… a gate that runs on
   every change."*
2. **"Never automatic; degradation is noticed by a person."** *"Monitoring is not a feedback loop… A dashboard
   collects and displays signals"* (M4:455-457); *"A drift with no trigger is invisible until a human happens
   to notice"* (M4:453); *"dashboards stay green for an entire quarter while answer quality quietly slid"*
   (M5:208); *"Set threshold alerts"* — cost over 150% of the 7-day average, p95 over the SLA (M2:736). The
   modules' own drift examples assume eval scores as a time series (M4:419, 448, 474), which on-demand evals
   cannot produce.

**What reconciles them without reversing the owner** (each needs the owner's word):
- *Activating a changed model or prompt with no eval run is an explicit, recorded override* — a reason typed
  at activation, a badge on the version. Nothing is refused. (Today it is recorded, but silently.)
- *The modules require a trigger, not automation* — *"some reviews fire on a schedule rather than at a
  threshold"* (M4:29). A dated row — "monthly: run the payables suite against baseline, by hand" — complies.
- *Passive flags from telemetry that already exists and costs nothing*: failure rate, escalation and
  approvals-needed rate, cost per run, p95, a duty not completed, thumbs-down rate — shown as "threshold
  crossed" on the dashboard, plus "the model changed since this agent was last evaluated" (M1:562, 574).
  No eval runs, no model spend. These are what make a person *suspect* degradation.

## What the modules confirm

Trials for non-determinism (M1:109-116); a curated set, a grader, a threshold set in advance (M1:1062); the
grading ladder — code, then a judge from a different model with constrained verdicts, then a person
(M2:85-89); thresholds from the business requirement, not from what the prototype scores (M2:102);
per-category floors over a mean (M1:1073, M2:65); "the prompt-model pairing is what you are actually
shipping" (M1:1238); recording exactly what the model saw (M1:380, 997; M2:592-597); deterministic
authorization as the enforcing layer (M3:221; M1:1516); a human gate before irreversible action (M3:456);
shadow over live A/B at low traffic (M2:728) — which is what "record, don't execute" is; immutable versions
with a way back (M5:64, 77).

## Changes I would fold into the eval design (no decision needed — they make it correct)

| # | Change | Why |
|---|---|---|
| 1 | **Baseline and candidate run against the same frozen data**, snapshot id on the run | M1:1071 "runs both models against the same set" — live books differ between two runs, so a delta could be the data's |
| 2 | **Suites go STALE**: each suite and case records the persona and skill hashes it was reviewed against; a run on different hashes says so | M2:114-120 "the highest risk moment… is when evals are present and out of date" |
| 3 | **Stale-memory cases**: plant a remembered figure that contradicts the books; hard-assert the reported number equals this run's tool result | M1:750, 785-801 "retrieval is for stable knowledge… tool use is for live state"; failures are "fluent, confident, and wrong" |
| 4 | **Coverage grader**: bills checked = open bills in the system of record; every number in a report traces to a tool result | M1:633-660 "results returned must equal units dispatched" |
| 5 | **Stopping behaviour asserted**: finished inside turn and time limits, no repeated tool loops | M2:238 "eval the agent's stopping behavior, not just its output quality" |
| 6 | **p50 / p95 from the ledger**, per call and per run; budgets stated as p95; cache read-to-write ratio per agent | M2:208-218; M2:336 (a once-a-day duty may mostly pay the cache-write premium) |
| 7 | **Judge verdicts labelled "uncalibrated" and kept out of pass thresholds** until checked against human labels | M2:93 an uncalibrated judge is "worse than no automated grade" |
| 8 | **Case data-sensitivity restricts which judge and which provider may see it** | M1:1448-1458; M3:554-559 |
| 9 | **The decomposition map is written BEFORE the cases** — what the model, SQL and people each own in the payables check | M1:321-336, 1744 |
| 10 | **Outcome signals become each agent's success rate**: approvals approved/rejected, handler refusals, a person reversing an agent's work | M2:597, 735 |
| 11 | **Each comparison records its hypothesis and primary metric first**, and reports the smallest effect its sample could detect | M2:704-711, 790 |
| 12 | **The cap is a suite setting** (default 5) and volume comes from code-graded cases | M2:118 "the bigger risk is under-evaluating" |

One question the modules raise about the first workflow itself: *"If you could have written the steps in
code, you could have used a workflow"* (M1:556). If Sasha's morning check always takes the same few tool
paths (the stored tool events will show it), it should be a deterministic workflow with a model writing the
summary — cheaper, auditable, and a different thing to evaluate.

## Safety gaps the modules expose in the platform (not the eval design)

1. **Tool results and recalled memory are not screened** — *"the dominant injection vector in enterprise
   deployments… screen retrieved content and tool outputs before they are appended"* (M3:229); *"instructions
   are not enforcement"* (M3:79). The only defence today is a sentence in the persona. Vendor names, memos,
   the shared inbox and shared memory can all carry instructions.
2. **The prompt ledger is an unminimised store of business data** with no retention rule or redaction
   (M3:164, 191, 366; M2:565, 603). I made it more complete today; it now needs a policy.
3. **Third-party model providers have no control entry** — terms, retention, training use, region, and which
   data classes may go to which provider (M3:554-559). Three providers are live as of today.
4. **Each guardrail's fail direction is unchosen and untested** — what happens when the ledger cannot write,
   the approval lookup errors, a token cannot be verified (M3:201, 239).
5. **Approval volume** — *"requiring sign-off on every action adds friction without meaningful safety gain"*
   (M3:464). One approver; watch the queue as agents gain writes.
6. **The assistant ignores `stop_reason: refusal`** (M3:231) and its 469-tool surface contradicts *"constrain
   the tool set to the minimum required"* (M2:238, 570) — tool search is a safety item, not just a cost one.

## Lifecycle artefacts the modules require and the platform lacks (M4, M5)

1. **Feedback-loop table** — signal, numeric trigger, owner, action, cadence; *"should exist before launch"*
   (M4:413, 457). About seven rows, all from signals that already exist.
2. **The before-metric** — *"Capture the before metric at the start… Without the before number, there is no
   story"* (M4:676-680). The agents already run; the baseline erodes daily. For payables: overdue bills,
   duplicates caught before payment, the owner's minutes a day.
3. **Runbook** — symptom, likely architecture cause, first action, escalation path (M5:194-208).
4. **Decision log** — decision and date, rejected alternatives, tradeoff, owner, evidence (M4:516-521).
   Decisions live in specs and commit messages today.
5. **Discovery translation table** per agent — must do / must not do / must cost / must prove (M4:75-93);
   each suite's product promise traces to a row.
6. **SLAs** — measured, breach, consequence (M4:393-405).
7. **Verification checklist** on a prompt, skill or tool change — correctness, security, maintainability,
   human understanding (M5:137-172). Advisory.
8. **A person's verdict on a run** — the cheapest drift signal (M4:449). Already proposed.
9. **Control register** — obligation, control, owner, evidence, revalidation date, fail direction (M3:172,
   544-571; M4:504). An on-demand eval can only be register evidence if a revalidation date makes someone
   run it.
