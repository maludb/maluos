"""The eval runner (docs/build-specs/eval-runner.md) — on demand, advisory, and it never writes.

A run takes a set's active cases, runs each of them three times as ordinary agent runs with
trigger='eval', grades each trial, and scores what it managed to grade. It blocks nothing: a
failing run is a fact on a screen for a person who went looking, not a gate and not a page at 3am
(owner, 2026-09-20).

The one rule: an eval run cannot change anything. That is enforced in mcp/actions_server.py, at the
MCP boundary, by asking the RUN ROW whether its trigger is 'eval'. Nothing here is load-bearing for
it — this module could be wrong in every other way and an evaluation would still be safe to run.
"""
from __future__ import annotations

import asyncio
import json
import logging

from . import grading, store, jev

log = logging.getLogger("agent_runner.evals")


class EvaluationUnsafe(Exception):
    """An evaluation changed something. It is stopped at once and says so: a score from a run that
    wrote to the business is worthless, and the writing matters far more than the score."""

TRIALS = 3                      # settled 2026-09-20; all three must pass for the case to pass
TRIAL_POLL_SECONDS = 3
TRIAL_TIMEOUT_SECONDS = 900


async def start(eval_run_id: int, launch) -> None:
    """Run one evaluation to completion. `launch` is service.launch — the single door every agent
    run goes through, so an eval trial is started exactly as a duty or a person starts one."""
    try:
        await _run(eval_run_id, launch)
    except EvaluationUnsafe as unsafe:
        log.error("eval run %s STOPPED: %s", eval_run_id, unsafe)
        await store.finish_eval_run(eval_run_id, status="error", score=None, passed=0, total=0,
                                    detail=str(unsafe))
    except Exception as exc:                        # noqa: BLE001
        log.exception("eval run %s failed", eval_run_id)
        await store.finish_eval_run(eval_run_id, status="error", score=None, passed=0, total=0,
                                    detail=f"The evaluation stopped: {exc}")


async def _run(eval_run_id: int, launch) -> None:
    run = await store.eval_run(eval_run_id)
    if run is None:
        return
    cases = await store.eval_cases(run["eval_set_id"])
    if not cases:
        await store.finish_eval_run(eval_run_id, status="error", score=None, passed=0, total=0,
                                    detail="The set has no active cases.")
        return

    await store.begin_eval_run(eval_run_id, len(cases))
    agent_model_key = (run.get("model_key") or "")
    results: list[dict] = []
    trial_runs: list[int] = []          # every trial started, so the cap sees what has been spent
    stopped: str | None = None

    for case in cases:
        # The cap is checked BETWEEN cases, so an evaluation can never eat the budget the agent
        # works from. One case may carry it slightly over; it stops before starting another.
        if await store.eval_run_cost(eval_run_id, trial_runs) >= store.EVAL_COST_CAP:
            stopped = (f"The evaluation stopped at its {store.EVAL_COST_CAP} cap after "
                       f"{len(results)} of {len(cases)} cases. What it graded is below.")
            break
        results.append(await _case(eval_run_id, run, case, agent_model_key, launch, trial_runs))

    graded = [r for r in results if not r["awaiting_person"]]
    awaiting = len(results) - len(graded)
    weight = sum(r["weight"] for r in graded)
    passed_weight = sum(r["weight"] for r in graded if r["passed"])
    score = round(100 * passed_weight / weight, 2) if weight else None

    detail = _detail(len(results), len(cases), len(graded), awaiting, stopped)
    status = "error" if score is None and not awaiting else (
        "passed" if score is not None and score >= float(run["pass_threshold"]) else "failed")
    await store.finish_eval_run(eval_run_id, status=status, score=score,
                                passed=sum(1 for r in graded if r["passed"]), total=len(cases),
                                detail=detail, trial_run_ids=trial_runs)
    log.info("eval run %s: %s (%s), %s graded, %s awaiting a person", eval_run_id, status, score,
             len(graded), awaiting)


def _detail(ran: int, total: int, graded: int, awaiting: int, stopped: str | None) -> str:
    """What the number does and does not cover. A score that is not yet the whole truth has to say
    so, or someone will quote it as though it were."""
    parts = [f"{graded} of {total} cases graded."]
    if awaiting:
        parts.append(f"{awaiting} await a person's grade and are NOT in the score — "
                     f"grading them will change it.")
    if ran < total and not stopped:
        parts.append(f"{total - ran} cases were not run.")
    if stopped:
        parts.append(stopped)
    return " ".join(parts)


async def _case(eval_run_id: int, run: dict, case: dict, agent_model_key: str, launch,
                trial_runs: list[int]) -> dict:
    """One case: three trials, all of which must pass. The first trial's run id is kept on the
    result so a reader can open what actually happened."""
    weight = float(case["weight"] or 1)
    if case["grader"] == "human":
        # A person has to say. The row exists so they can grade it (html/ai/evals/grade.php), and
        # it is excluded from the score until they do — never counted as a pass OR a fail.
        run_id = await _trial(eval_run_id, run, case, launch, trial_runs)
        await store.write_eval_result(eval_run_id, case["id"], run_id, passed=False, score=None,
                                      notes="Awaiting a person's grade.", grader_model_id=None)
        return {"passed": False, "weight": weight, "awaiting_person": True}

    trials: list[tuple[bool, float, str]] = []
    first_run_id: int | None = None
    judge_model_id: int | None = None
    jev_trials: list[dict] = []          # a JEV case: every trial's checks, kept in grader_detail

    for trial in range(TRIALS):
        run_id = await _trial(eval_run_id, run, case, launch, trial_runs)
        first_run_id = first_run_id or run_id
        if run_id is None:
            trials.append((False, 0.0, f"Trial {trial + 1}: the agent could not be run."))
            continue
        agent_run = await store.run_row(run_id)
        answer = (agent_run or {}).get("result")
        payload = await store.last_payload(run_id)
        expected = _json(case["expected"]) or {}

        # The rule this whole slice rests on, checked rather than trusted. The interception lives
        # at the MCP boundary; if it ever fails, the evaluation must stop at the FIRST trial —
        # not carry on writing while reporting a score.
        changed = await store.run_changed_anything(run_id)
        if changed:
            raise EvaluationUnsafe(
                f"Trial {trial + 1} of case {case['id']} CHANGED something ({', '.join(changed)}). "
                "An evaluation must change nothing. The evaluation was stopped; the write "
                "interception in mcp/actions_server.py needs looking at before evals are run again.")

        if (agent_run or {}).get("status") not in ("succeeded", "awaiting_approval"):
            trials.append((False, 0.0, f"Trial {trial + 1}: the run {(agent_run or {}).get('status')} — "
                                       f"{((agent_run or {}).get('error') or '')[:300]}"))
            continue
        if case["grader"] == "jev":
            transcript = grading.transcript_text(payload, _instructions(case), answer)
            t = await grading.grade_jev(dict(case, expected=expected, input=_json(case["input"])), transcript, eval_run_id)
            judge_model_id = t.pop("model_id", None) or judge_model_id
            jev_trials.append(t)
            trials.append((t["verdict"] == "passed", t["score"], jev.notes_for(trial + 1, t)))
            continue
        if case["grader"] == "exact":
            ok, score, why = grading.grade_exact(expected, answer)
        elif case["grader"] == "programmatic":
            ok, score, why = grading.grade_programmatic(expected, answer, payload)
        else:
            transcript = grading.transcript_text(payload, _instructions(case), answer)
            ok, score, why, judge_model_id = await grading.grade_rubric_llm(
                dict(case, expected=expected, input=_json(case["input"])), transcript, agent_model_key, eval_run_id)
        trials.append((ok, score, f"Trial {trial + 1}: {why}"))

    if case["grader"] == "jev":
        return await _jev_case_result(eval_run_id, case, weight, first_run_id, trials, jev_trials, judge_model_id)

    passed = all(ok for ok, _, _ in trials) and len(trials) == TRIALS
    mean = round(sum(s for _, s, _ in trials) / len(trials), 2) if trials else 0.0
    notes = "\n".join(note for _, _, note in trials)
    if not passed and any(ok for ok, _, _ in trials):
        notes = "NOT ALL THREE TRIALS AGREED — the agent is inconsistent here.\n" + notes
    await store.write_eval_result(eval_run_id, case["id"], first_run_id, passed=passed, score=mean,
                                  notes=notes[:4000], grader_model_id=judge_model_id)
    return {"passed": passed, "weight": weight, "awaiting_person": False}


async def _jev_case_result(eval_run_id: int, case: dict, weight: float, first_run_id: int | None,
                           trials: list[tuple[bool, float, str]], jev_trials: list[dict],
                           judge_model_id: int | None) -> dict:
    """A JEV case over its three trials: failed if any trial failed (a required check confidently
    failed, or the agent could not be run), awaiting a person if any trial was unsure (or JEV could
    not be asked), else passed. Awaiting is never counted as a pass or a fail."""
    ran_all = len(trials) == TRIALS and len(jev_trials) == TRIALS
    verdicts = [t["verdict"] for t in jev_trials]
    if not ran_all and len(jev_trials) < len(trials):
        verdict = "failed"                           # a trial whose agent could not be run is a failure
    elif "failed" in verdicts:
        verdict = "failed"
    elif "awaiting" in verdicts:
        verdict = "awaiting"
    else:
        verdict = "passed" if ran_all else "failed"
    mean = round(sum(sc for _, sc, _ in trials) / len(trials), 2) if trials else 0.0
    head = {"passed": "JEV: passed on all three trials.",
            "failed": "JEV: failed — a required check failed, or a trial could not be run.",
            "awaiting": "JEV was not sure — a person grades this case; it is not in the score until then."}[verdict]
    notes = head + "\n" + "\n".join(note for _, _, note in trials)
    await store.write_eval_result(eval_run_id, case["id"], first_run_id, passed=verdict == "passed", score=mean,
                                  notes=notes[:4000], grader_model_id=judge_model_id,
                                  awaiting_person=verdict == "awaiting",
                                  grader_detail={"grader": "jev", "model": jev.MODEL_KEY, "verdict": verdict,
                                                 "trials": jev_trials})
    return {"passed": verdict == "passed", "weight": weight, "awaiting_person": verdict == "awaiting"}


async def _trial(eval_run_id: int, run: dict, case: dict, launch, trial_runs: list[int]) -> int | None:
    """One attempt, as an ordinary agent run — ledgered, its events kept, visible in AI Ops like
    any other. That is deliberate: an evaluation is evidence, not a special case."""
    try:
        started = await launch(agent_member_id=run["agent_member_id"], trigger="eval",
                               instructions=_instructions(case), requested_by=run["started_by"],
                               config_version_id=run["config_version_id"])
    except Exception as exc:                        # noqa: BLE001
        log.warning("eval run %s: trial for case %s did not start: %s", eval_run_id, case["id"], exc)
        return None
    run_id = started["run_id"]
    trial_runs.append(run_id)
    for _ in range(TRIAL_TIMEOUT_SECONDS // TRIAL_POLL_SECONDS):
        row = await store.run_row(run_id)
        if row and row["status"] not in ("running", "queued"):
            return run_id
        await asyncio.sleep(TRIAL_POLL_SECONDS)
    return run_id


def _instructions(case: dict) -> str:
    """What the agent is asked. `eval_cases.input` is jsonb: its `instructions` (or `task`) is the
    request; anything else in it is context the case author wanted the agent to have."""
    data = _json(case["input"]) or {}
    if isinstance(data, str):
        return data
    # `text` is the shape the case form itself produces (eval_text_to_json wraps what a person
    # typed); the other three are what someone writing a case by hand or by tool would reach for.
    keys = ("instructions", "task", "prompt", "text")
    task = next((data[k] for k in keys if data.get(k)), None)
    extra = {k: v for k, v in data.items() if k not in keys}
    if not task:
        return json.dumps(data, default=str)
    return task if not extra else f"{task}\n\nContext for this task:\n{json.dumps(extra, default=str)}"


def _json(value):
    if isinstance(value, (dict, list)) or value is None:
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


async def compare_to_baseline(eval_run_id: int, baseline_run_id: int | None) -> list[dict]:
    """Case by case, not score to score: the answer that matters is WHICH cases used to pass and
    now do not. A score moving from 82 to 79 tells you nothing about what broke."""
    if baseline_run_id is None:
        return []
    return await store.eval_case_diff(eval_run_id, baseline_run_id)
