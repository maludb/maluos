"""How an eval case is graded (docs/build-specs/eval-runner.md).

Four graders, three of which are deterministic and one of which is a model. None of them executes
anything the case supplies: `programmatic` runs fixed checks over the transcript, never code from
`eval_cases.expected`.

The transcript is not rebuilt here — `memory.transcript_from_payload()` already turns a run's last
ledger payload into the whole conversation, tool calls included, which is exactly what a grader has
to see. Under an evaluation a write tool answers `recorded`, so what the agent WOULD have written is
in the transcript as an ordinary tool result.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from . import config, store
from .memory import transcript_from_payload

log = logging.getLogger("agent_runner.grading")

# Settled 2026-09-20 (docs/build-specs/eval-evidence.md): the judge is Sonnet 5, or DeepSeek V4 Pro
# when the agent under test is itself on Sonnet — a model should not mark its own homework.
JUDGE_MODEL = "hermes:claude-sonnet-5"
JUDGE_ALTERNATE = "hermes:deepseek-v4-pro"

JUDGE_SYSTEM = """You are grading one attempt by an AI agent employed by a business, against a
rubric its owner wrote. You are not the agent and you are not its advocate.

Judge ONLY what the transcript shows. If the rubric asks for something the transcript does not
show, it did not happen. Writing was disabled for this attempt: a tool answering "recorded" means
the agent correctly asked for that write, and should be judged as though the write succeeded.

Answer with JSON and nothing else:
{"passed": true|false, "score": 0-100, "why": "<one or two sentences, concrete>"}"""


def transcript_text(payload: dict | None, instructions: str, answer: str | None) -> str:
    """The conversation as plain text for a grader to read — or, when the payload is gone, just
    what was asked and answered. A grader is told which it got, so it never treats a missing
    transcript as an empty one."""
    messages = transcript_from_payload((payload or {}).get("context"), (payload or {}).get("response"),
                                       instructions) if payload else []
    if not messages:
        return (f"[The transcript could not be recovered; only the request and the final answer are "
                f"available.]\n\nASKED:\n{instructions}\n\nANSWERED:\n{answer or '(nothing)'}")
    return "\n\n".join(f"{m['role'].upper()}: {m['text']}" for m in messages)


def tools_called(payload: dict | None) -> list[str]:
    """Every tool the attempt called, in order. transcript_from_payload writes them as
    `[called <tool> <args>]`, which is the one place arguments survive outside prompt_payloads."""
    if not payload:
        return []
    text = json.dumps(payload.get("context") or {})
    return re.findall(r"\[called ([A-Za-z0-9_]+)", text) + re.findall(r'"name":\s*"([A-Za-z0-9_]+)"', text)


def grade_exact(expected: dict, answer: str | None) -> tuple[bool, float, str]:
    want = str(expected.get("answer") or "").strip().casefold()
    got = (answer or "").strip().casefold()
    if not want:
        return False, 0.0, "The case is graded `exact` but names no expected answer."
    ok = want == got
    return ok, 100.0 if ok else 0.0, "Exactly the expected answer." if ok else f"Expected {want!r}."


def grade_programmatic(expected: dict, answer: str | None, payload: dict | None) -> tuple[bool, float, str]:
    """Fixed checks, all of which must hold. Nothing from the case is executed — these are the only
    four things a `programmatic` case can assert, and a case asking for anything else says so."""
    answer_l = (answer or "").casefold()
    called = [t.casefold() for t in tools_called(payload)]
    checks: list[tuple[bool, str]] = []

    for tool in expected.get("tools") or []:
        hit = any(str(tool).casefold() in c for c in called)
        checks.append((hit, f"called {tool}" if hit else f"did NOT call {tool}"))
    for needle in expected.get("contains") or []:
        hit = str(needle).casefold() in answer_l
        checks.append((hit, f"said {needle!r}" if hit else f"did NOT say {needle!r}"))
    for needle in expected.get("not_contains") or []:
        clear = str(needle).casefold() not in answer_l
        checks.append((clear, f"did not say {needle!r}" if clear else f"said {needle!r}, which it should not"))
    if expected.get("no_writes"):
        wrote = "would_have_called" in json.dumps(payload or {})
        checks.append((not wrote, "attempted no write" if not wrote else "attempted a write"))

    if not checks:
        return False, 0.0, ("The case is graded `programmatic` but asserts nothing. Give it "
                            "expected.tools, expected.contains, expected.not_contains or expected.no_writes.")
    passed = sum(1 for ok, _ in checks if ok)
    return passed == len(checks), round(100.0 * passed / len(checks), 2), "; ".join(note for _, note in checks)


async def grade_rubric_llm(case: dict, transcript: str, agent_model_key: str,
                           eval_run_id: int) -> tuple[bool, float, str, int | None]:
    """A model reads the rubric and the transcript and says whether it passed. The call goes
    through the ledger proxy like every other, so the judging is itself in the prompt ledger."""
    judge_key = JUDGE_ALTERNATE if (agent_model_key or "").endswith("claude-sonnet-5") else JUDGE_MODEL
    judge = await store.model_by_key(judge_key) or await store.model_by_key(JUDGE_MODEL)
    if judge is None:
        return False, 0.0, f"No judge model is registered ({judge_key}); the case could not be graded.", None
    # The judge key names the eval RUN, so the proxy is told here which model is doing the judging.
    store.set_judge_model(eval_run_id, judge["model_key"])

    asked = (f"RUBRIC:\n{case.get('rubric') or '(none given)'}\n\n"
             f"WHAT THE AGENT WAS ASKED:\n{json.dumps(case.get('input'), default=str)[:4000]}\n\n"
             f"EXPECTED (may be empty):\n{json.dumps(case.get('expected'), default=str)[:2000]}\n\n"
             f"TRANSCRIPT:\n{transcript[:60000]}")
    try:
        answer = await _ask_judge(judge, asked, eval_run_id)
    except Exception as exc:  # noqa: BLE001 — a judge that cannot be reached is not a failed case
        log.warning("eval run %s: judge unreachable: %s", eval_run_id, exc)
        return False, 0.0, f"The judge could not be reached: {exc}", judge["id"]

    try:
        verdict = json.loads(re.search(r"\{.*\}", answer, re.S).group(0))
    except (AttributeError, ValueError):
        return False, 0.0, f"The judge did not answer in the agreed form. It said: {answer[:400]}", judge["id"]
    score = float(verdict.get("score") or 0)
    return bool(verdict.get("passed")), max(0.0, min(100.0, score)), str(verdict.get("why") or "")[:4000], judge["id"]


async def _ask_judge(judge: dict, asked: str, eval_run_id: int) -> str:
    """One call, through the run's own ledger proxy credentials. The judge holds no tools: it reads
    and answers, and cannot touch the business even in principle."""
    key = store.mint_judge_key(eval_run_id)   # sync: it is an HMAC, not a database read
    base = f"http://127.0.0.1:{config.PROXY_PORT}"
    wire = config.PROVIDERS.get(judge["provider"], ("", "", "openai"))[2]
    async with httpx.AsyncClient(timeout=180.0) as c:
        if wire == "anthropic":
            r = await c.post(f"{base}/anthropic/v1/messages",
                             headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                             json={"model": judge["provider_model_id"], "max_tokens": 1024,
                                   "system": JUDGE_SYSTEM, "messages": [{"role": "user", "content": asked}]})
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json().get("content") or [])
        r = await c.post(f"{base}/openai/v1/chat/completions",
                         headers={"authorization": f"Bearer {key}"},
                         json={"model": judge["provider_model_id"], "max_tokens": 1024,
                               "messages": [{"role": "system", "content": JUDGE_SYSTEM},
                                            {"role": "user", "content": asked}]})
        r.raise_for_status()
        return ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""


async def grade_jev(case: dict, transcript: str, eval_run_id: int) -> dict:
    """One trial graded by JEV (db/144): every check and the injection guard in one call through the
    ledger proxy. A JEV that cannot be asked — not configured, unreachable, refused — leaves the
    trial awaiting a person, never failed: the grader's trouble is not the agent's."""
    from . import jev
    checks = _checks(case.get("checks"))
    model = await store.model_by_key(jev.MODEL_KEY)
    try:
        answers = await jev.ask(eval_run_id, jev.build_state(case, transcript), jev.build_questions(checks))
    except Exception as exc:  # noqa: BLE001
        log.warning("eval run %s: JEV could not be asked: %s", eval_run_id, exc)
        return {"verdict": "awaiting", "score": 0.0, "checks": {}, "guard": 0.0,
                "error": f"JEV could not be asked: {str(exc)[:300]}", "model_id": model["id"] if model else None}
    t = jev.trial_verdict(checks, answers)
    t["model_id"] = model["id"] if model else None
    return t


def _checks(value) -> list[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []
