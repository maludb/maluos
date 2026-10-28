"""Everything the runner reads and writes, as the app_runner role (db/097, db/100).

The role can insert runs and ledger rows and read what rendering a profile needs — and nothing
else. No business records, no secrets, no activity log: an agent reaches records through MCP
under its own identity, and the runner asks PHP to log (html/agents/run-callback.php).
"""
from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal

import uuid

import asyncpg

from . import config, run_token

log = logging.getLogger("agent_runner.store")

_pool: asyncpg.Pool | None = None


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=config.get("RUNNER_DB_HOST", "127.0.0.1"), port=int(config.get("RUNNER_DB_PORT", "5432")),
            database=config.get("RUNNER_DB_NAME", "maludb_os"), user=config.require("RUNNER_DB_USER"),
            password=config.require("RUNNER_DB_PASSWORD"), min_size=1, max_size=6)
    return _pool


class RunRefused(Exception):
    """The run cannot start; the message is for the person who asked."""


async def load_agent(member_id: int, config_version_id: int | None = None) -> dict:
    """The agent as the harness needs it: member, profile, config version, model, manager.

    `config_version_id` names the version to run; omitted, it is the ACTIVE one. An evaluation
    passes it so a prompt or model change can be weighed BEFORE it goes live (owner, 2026-09-20) —
    running a version never activates it, and the version named must belong to this agent."""
    p = await pool()
    async with p.acquire() as con:
        row = await con.fetchrow("""
            SELECT m.id AS member_id, m.display_name, m.status AS member_status, m.job_title, m.timezone,
                   ap.status AS agent_status, ap.agent_kind, ap.role_key, ap.description,
                   ap.monthly_budget_amount, ap.budget_currency, ap.home_location_id,
                   ap.current_config_version_id, mgr.display_name AS manager_name,
                   cv.id AS config_version_id, cv.version_no, cv.job_description, cv.runtime_config, cv.model_id
              FROM members m
              JOIN agent_profiles ap ON ap.member_id = m.id
              LEFT JOIN members mgr ON mgr.id = ap.manager_member_id
              LEFT JOIN agent_config_versions cv
                     ON cv.id = COALESCE($2::bigint, ap.current_config_version_id)
                    AND cv.agent_member_id = m.id
             WHERE m.id = $1 AND m.member_kind = 'agent'""", member_id, config_version_id)
        if row is None:
            raise RunRefused("That member is not an agent.")
        agent = dict(row)
        if agent["member_status"] != "active" or agent["agent_status"] != "active":
            raise RunRefused("The agent is not active.")
        if config_version_id is not None and agent["config_version_id"] is None:
            raise RunRefused(f"Configuration version {config_version_id} does not belong to this agent.")
        if agent["current_config_version_id"] is None and config_version_id is None:
            raise RunRefused("The agent has no active configuration version.")
        model = await con.fetchrow("SELECT * FROM model_registry WHERE id = $1", agent["model_id"])
        if model is None or model["status"] != "active":
            raise RunRefused("The agent's model is not active in the model registry.")
        agent["model"] = dict(model)
        if model["auth_mode"] == "claude_subscription":
            if model["harness"] != "claude_agent_sdk":
                raise RunRefused("A Claude subscription is only used through the official Claude Code CLI (the claude_agent_sdk harness).")
            # The owner's Max login (claude-subscription-auth.md): off unless switched on in runner.env, and one run at a
            # time because every agent on it shares one plan's rate limit (owner, 2026-09-29).
            if not config.subscription_enabled():
                raise RunRefused("This agent's model bills to a Claude subscription, and subscription use is switched off "
                                 "(ALLOW_CLAUDE_SUBSCRIPTION and the token in runner.env). Nothing was run.")
            going = await con.fetchval("""SELECT count(*) FROM agent_runs r JOIN model_registry mr ON mr.id = r.model_id
                                           WHERE r.status = 'running' AND mr.auth_mode = 'claude_subscription'""")
            if going >= config.SUBSCRIPTION_MAX_CONCURRENT:
                raise RunRefused("A subscription run is already going and the plan's limit is shared, so they run one at a time. Try again shortly.")
        agent["runtime_config"] = _json(agent["runtime_config"]) or {}
        departments = await con.fetch("""
            SELECT d.id, d.name FROM departments d JOIN department_members dm ON dm.department_id = d.id
             WHERE dm.member_id = $1 AND dm.left_at IS NULL ORDER BY dm.is_primary DESC, d.name""", member_id)
        agent["departments"] = [r["name"] for r in departments]
        agent["department_ids"] = [r["id"] for r in departments]       # the shared-memory scope set
        # Onboarding = the job description plus the department handbook (db/107: the runner reads
        # handbooks through a view and nothing else in Documents).
        handbooks = await con.fetch("""
            SELECT department_id, department_name, document_id, title, body_markdown
              FROM runner_department_handbooks WHERE department_id = ANY($1::bigint[])""",
            agent["department_ids"])
        order = {dept: i for i, dept in enumerate(agent["department_ids"])}
        agent["handbooks"] = sorted((dict(r) for r in handbooks), key=lambda h: order[h["department_id"]])
        agent["endpoints"] = await _granted_endpoints(con, member_id)
        agent["org"] = await _org_place(con, member_id)
    return agent


async def _org_place(con, member_id: int) -> dict:
    """Where the agent sits in the orchestrator tree (db/154) and who it may message (db/155): its
    person (when it is someone's assistant), its orchestrator(s), its roster, and the leads beside it."""
    principal = await con.fetchval("""
        SELECT m.display_name FROM agent_profiles p JOIN members m ON m.id = p.principal_member_id
         WHERE p.member_id = $1""", member_id)
    parents = await con.fetch("""
        SELECT m.display_name, p.principal_member_id IS NOT NULL AS is_assistant
          FROM agent_subagents s JOIN members m ON m.id = s.orchestrator_member_id
          JOIN agent_profiles p ON p.member_id = s.orchestrator_member_id
         WHERE s.subagent_member_id = $1 AND s.removed_at IS NULL ORDER BY m.display_name""", member_id)
    roster = await con.fetch("""
        SELECT m.display_name, p.agent_kind,
               (SELECT string_agg(d.name::text, ', ' ORDER BY d.name) FROM department_members dm
                  JOIN departments d ON d.id = dm.department_id
                 WHERE dm.member_id = m.id AND dm.left_at IS NULL) AS departments
          FROM agent_subagents s JOIN members m ON m.id = s.subagent_member_id
          JOIN agent_profiles p ON p.member_id = s.subagent_member_id
         WHERE s.orchestrator_member_id = $1 AND s.removed_at IS NULL AND m.status = 'active'
         ORDER BY m.display_name""", member_id)
    peers = await con.fetch("""
        SELECT m.display_name FROM agent_subagents s JOIN members m ON m.id = s.subagent_member_id
          JOIN agent_profiles p ON p.member_id = s.subagent_member_id AND p.agent_kind = 'orchestrator'
         WHERE s.orchestrator_member_id = agent_parent_orchestrator($1) AND s.removed_at IS NULL
           AND s.subagent_member_id <> $1 AND m.status = 'active' ORDER BY m.display_name""", member_id)
    return {"principal": principal, "parents": [dict(r) for r in parents],
            "roster": [dict(r) for r in roster], "peers": [r["display_name"] for r in peers]}


async def _granted_endpoints(con, member_id: int) -> list[dict]:
    """The MCP endpoints the agent holds live tool grants on, each with its granted tool names.
    The same liveness rule as mcp_agent_tool_grants_for() (db/099) and the db/075 trigger."""
    rows = await con.fetch("""
        SELECT e.id, e.name, e.url, e.auth_kind, a.app_key, g.tool_name,
               CASE WHEN a.app_key = 'platform' THEN 'builtin' ELSE coalesce(c.kind, 'external') END AS catalog_kind
          FROM agent_tool_grants g
          JOIN application_endpoints e ON e.id = g.application_endpoint_id
          JOIN applications a          ON a.id = e.application_id
          LEFT JOIN application_catalog c ON c.catalog_key = a.catalog_key
         WHERE g.agent_member_id = $1 AND g.revoked_at IS NULL
           AND e.kind = 'mcp' AND e.agent_reachable AND e.status = 'active'
         ORDER BY e.id, g.tool_name""", member_id)
    endpoints: dict[int, dict] = {}
    for r in rows:
        ep = endpoints.setdefault(r["id"], {"id": r["id"], "name": r["name"], "url": r["url"],
                                            "auth_kind": r["auth_kind"], "app_key": r["app_key"],
                                            "catalog_kind": r["catalog_kind"], "tools": []})
        ep["tools"].append(r["tool_name"])
    return list(endpoints.values())


async def create_run(*, agent: dict, trigger: str, instructions: str, request_id: str, harness: str,
                     sdk_version: str, requested_by: int | None, duty_id: int | None,
                     parent_run_id: int | None) -> int:
    p = await pool()
    try:
        async with p.acquire() as con:
            return await con.fetchval("""
                INSERT INTO agent_runs (agent_member_id, acting_member_id, location_id, trigger, duty_id,
                                        config_version_id, model_id, harness, sdk_version, request_id,
                                        instructions, requested_by, parent_run_id, currency)
                VALUES ($1, $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) RETURNING id""",
                agent["member_id"], agent["home_location_id"], trigger, duty_id,
                # The version actually being run, which for an evaluation may not be the live one.
                agent["config_version_id"], agent["model_id"], harness, sdk_version, request_id,
                instructions, requested_by, parent_run_id, agent["model"].get("currency") or "USD")
    except asyncpg.UniqueViolationError as exc:   # agent_runs_one_running_per_agent
        raise RunRefused("The agent is already running; one run at a time per agent.") from exc


async def note_prepared(run_id: int, profile_hash: str, skills: list) -> None:
    p = await pool()
    async with p.acquire() as con:
        await con.execute("UPDATE agent_runs SET profile_hash = $2, skills = $3::jsonb WHERE id = $1",
                          run_id, profile_hash, json.dumps(skills))


async def pending_approval_for(run_id: int) -> int | None:
    """The approval request this run is waiting on, if an action it took paused for its manager."""
    p = await pool()
    async with p.acquire() as con:
        return await con.fetchval("""SELECT id FROM approval_requests
                                      WHERE agent_run_id = $1 AND status = 'pending' ORDER BY id LIMIT 1""", run_id)


async def finish_run(run_id: int, *, status: str, result: str | None, error: str | None,
                     usage_report: dict | None, approval_request_id: int | None = None) -> dict:
    """Close the run. Totals come from the LEDGER, not from the harness's own report."""
    p = await pool()
    async with p.acquire() as con:
        totals = await con.fetchrow("""
            SELECT COALESCE(sum(input_tokens),0) AS i, COALESCE(sum(output_tokens),0) AS o,
                   COALESCE(sum(cache_read_tokens),0) AS cr, COALESCE(sum(cache_write_tokens),0) AS cw,
                   COALESCE(sum(cost),0) AS cost, count(*) AS calls
              FROM prompt_ledger WHERE agent_run_id = $1""", run_id)
        await con.execute("""
            UPDATE agent_runs SET status = $2, result = $3, error = $4, usage_report = $5::jsonb,
                   input_tokens = $6, output_tokens = $7, cache_read_tokens = $8, cache_write_tokens = $9,
                   cost = $10, approval_request_id = $11, finished_at = now()
             WHERE id = $1""", run_id, status, result, error,
            json.dumps(usage_report) if usage_report is not None else None,
            totals["i"], totals["o"], totals["cr"], totals["cw"], totals["cost"], approval_request_id)
    return {"calls": totals["calls"], "cost": str(totals["cost"]),
            "input_tokens": totals["i"], "output_tokens": totals["o"]}


async def get_run(run_id: int) -> dict | None:
    p = await pool()
    async with p.acquire() as con:
        row = await con.fetchrow("""
            SELECT id, agent_member_id, status, trigger, harness, sdk_version, request_id, instructions,
                   result, error, cost, currency, input_tokens, output_tokens, started_at, finished_at, parent_run_id
              FROM agent_runs WHERE id = $1""", run_id)
    return dict(row) if row else None


async def run_for_proxy(run_id: int) -> dict | None:
    """What the ledger proxy needs to know about the run a key names."""
    p = await pool()
    async with p.acquire() as con:
        row = await con.fetchrow("""
            SELECT r.id, r.status, r.agent_member_id, r.acting_member_id, r.location_id, r.harness,
                   r.sdk_version, r.request_id, r.model_id, r.trigger,
                   -- The budget is part of the immutable config version the run used; activating a
                   -- version does not copy it onto the profile. The profile's figure is the fallback.
                   COALESCE(cv.monthly_budget_amount, ap.monthly_budget_amount) AS monthly_budget_amount
              FROM agent_runs r
              LEFT JOIN agent_profiles ap        ON ap.member_id = r.agent_member_id
              LEFT JOIN agent_config_versions cv ON cv.id = r.config_version_id
             WHERE r.id = $1""", run_id)
        if row is None:
            return None
        run = dict(row)
        # Eval spend is separate from agent budgets (settled 2026-09-20): evaluating an agent must
        # never eat the budget it works from, or a morning's evals would silence it for the day.
        # The evaluation's own cap governs instead, checked by the eval runner between cases.
        if run["trigger"] == "eval":
            run["monthly_budget_amount"] = None
        run["model"] = dict(await con.fetchrow("SELECT * FROM model_registry WHERE id = $1", run["model_id"]))
    return run


async def month_to_date_cost(agent_member_id: int) -> Decimal:
    p = await pool()
    async with p.acquire() as con:
        return Decimal(str(await con.fetchval("""
            -- money plus notional: a subscription call costs nothing but still counts against the agent's budget (owner, 2026-09-29)
            SELECT COALESCE(sum(cost + notional_cost), 0) FROM prompt_ledger
             WHERE agent_member_id = $1 AND occurred_at >= date_trunc('month', now())""", agent_member_id)))


async def write_ledger(*, run: dict, status: str, provider_request_id: str | None, tokens: dict,
                       latency_ms: int, cost: Decimal, context: dict | None, response, error_code: str | None = None,
                       error_message: str | None = None, call_kind: str = "messages") -> int:
    """One prompt_ledger row and its prompt_payloads row, in one transaction. On a subscription model the money is 0
    and the list price the API would have charged goes in notional_cost (db/164) — so no statement mistakes it for spend."""
    model = run["model"]
    subscription = model.get("auth_mode") == "claude_subscription"
    billing, notional, cost = ("subscription", cost, Decimal(0)) if subscription else ("api", Decimal(0), cost)
    body = json.dumps({"context": context, "response": response}, sort_keys=True, default=str).encode()
    p = await pool()
    async with p.acquire() as con, con.transaction():
        ledger_id = await con.fetchval("""
            INSERT INTO prompt_ledger (agent_run_id, agent_member_id, acting_member_id, location_id, harness,
                   sdk_version, provider, model_id, provider_model_id, request_id, provider_request_id,
                   call_kind, status, error_code, error_message, input_tokens, output_tokens,
                   cache_read_tokens, cache_write_tokens, latency_ms, cost, currency, billing, notional_cost,
                   application_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$22,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$23,$24,$25)
            RETURNING id""",
            run["id"], run["agent_member_id"], run["acting_member_id"], run["location_id"], run["harness"],
            run["sdk_version"], model["provider"], model["id"], model["provider_model_id"], run["request_id"],
            provider_request_id, status, error_code, (error_message or None) and error_message[:2000],
            tokens["input"], tokens["output"], tokens["cache_read"], tokens["cache_write"], latency_ms,
            cost, model.get("currency") or "USD", call_kind, billing, notional, run.get("application_id"))
        await con.execute("""
            INSERT INTO prompt_payloads (ledger_id, context, response, byte_size, sha256)
            VALUES ($1, $2::jsonb, $3::jsonb, $4, $5)""",
            ledger_id, json.dumps(context, default=str), json.dumps(response, default=str), len(body),
            hashlib.sha256(body).hexdigest())
    return ledger_id


async def app_credential_for_proxy(token_hash: str) -> dict | None:
    """K24 (db/171): what the proxy needs about an APPLICATION's own model call — shaped like run_for_proxy's answer
    (`id` None: no agent run behind it; `agent_member_id` None) plus the models it may name. The model itself is
    chosen from the request body by the proxy, so `model` is None here."""
    p = await pool()
    async with p.acquire() as con:
        row = await con.fetchrow("SELECT * FROM app_model_credential_resolve($1)", token_hash)
        if row is None:
            return None
        models = [dict(m) for m in await con.fetch(
            "SELECT * FROM model_registry WHERE id = ANY($1::bigint[]) AND status = 'active' AND auth_mode = 'api_key'",
            list(row["allowed_model_ids"]))]
    return {"id": None, "is_application": True, "application_id": row["application_id"],
            "application_name": row["application_name"], "credential_id": row["credential_id"],
            "agent_member_id": None, "acting_member_id": row["acting_member_id"], "location_id": None,
            "harness": "application", "sdk_version": None, "request_id": f"app-{row['application_id']}-{uuid.uuid4().hex[:16]}",
            "model_id": None, "model": None, "allowed_models": models, "call_kind": "messages",
            "monthly_budget_amount": row["monthly_budget_amount"]}


async def application_month_cost(application_id: int) -> Decimal:
    p = await pool()
    async with p.acquire() as con:
        return Decimal(str(await con.fetchval("SELECT application_model_month_cost($1)", application_id)))


async def add_content_flags(agent_member_id: int, run_id: int | None, flags: list[dict]) -> None:
    """Memory items withheld from a run because they read like instructions (db/123)."""
    p = await pool()
    async with p.acquire() as con:
        for f in flags:
            await con.fetchval("SELECT record_content_flag($1,$2,$3,$4,$5,$6,'withheld')", agent_member_id, run_id,
                               f["source"], str(f.get("source_name") or ""), f["pattern"], f["excerpt"])


EVENT_COLUMNS = ("tool_name", "tool_call_id", "status", "error_type", "error_message", "api_request_id")


async def add_event(run_id: int, seq: int, event: dict) -> None:
    """Keep one observed event (db/122). Telemetry must never break a run: the caller ignores failures."""
    known = {k: (str(event[k])[:2000] if event.get(k) is not None else None) for k in EVENT_COLUMNS}
    duration = event.get("duration_ms")
    if duration is None and isinstance(event.get("api_duration"), (int, float)):
        duration = event["api_duration"] * 1000                  # the harness reports API time in seconds
    try:
        duration = max(0, int(duration)) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    rest = {k: v for k, v in event.items() if k not in EVENT_COLUMNS and k not in ("event", "duration_ms")}
    p = await pool()
    async with p.acquire() as con:
        await con.execute("""
            INSERT INTO agent_run_events (agent_run_id, seq, event, tool_name, tool_call_id, status, error_type,
                   error_message, api_request_id, duration_ms, detail)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb) ON CONFLICT (agent_run_id, seq) DO NOTHING""",
            run_id, seq, str(event.get("event") or "event")[:80], known["tool_name"], known["tool_call_id"],
            known["status"], known["error_type"], known["error_message"], known["api_request_id"], duration,
            json.dumps(rest, default=str)[:20000])


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


async def last_payload(run_id: int) -> dict | None:
    """The run's last successful agent call: its context holds the whole conversation.

    A call that carried tools is preferred, because a harness with auxiliary model slots (Hermes)
    makes small toolless calls of its own and those are not the conversation. It is a PREFERENCE,
    not a filter: an agent with no tool grants at all makes only toolless calls, and requiring
    tools told it "no model call was recorded" for a run that had just answered (found by the
    Claude harness slice, run 34)."""
    p = await pool()
    async with p.acquire() as con:
        row = await con.fetchrow("""
            SELECT pp.context, pp.response FROM prompt_ledger pl JOIN prompt_payloads pp ON pp.ledger_id = pl.id
             WHERE pl.agent_run_id = $1 AND pl.status = 'ok'
             ORDER BY (jsonb_array_length(COALESCE(pp.context->'tools', '[]'::jsonb)) > 0) DESC, pl.id DESC
             LIMIT 1""", run_id)
    return {"context": _json(row["context"]), "response": _json(row["response"])} if row else None


async def skill_assignments_for(agent: dict) -> list[dict]:
    """Every live assignment that reaches this agent: org, its departments, its role, itself, and
    the applications it may use or is the expert on (db/130)."""
    p = await pool()
    async with p.acquire() as con:
        rows = await con.fetch("""
            SELECT skill_name, pinned_bundle_hash, scope_kind FROM skill_assignments
             WHERE revoked_at IS NULL
               AND (scope_kind = 'org'
                 OR (scope_kind = 'department' AND department_id = ANY($1::bigint[]))
                 OR (scope_kind = 'role' AND role_key = $2)
                 OR (scope_kind = 'agent' AND agent_member_id = $3)
                 OR (scope_kind = 'application'
                     AND application_id = ANY (app_agent_skill_application_ids($3))))""",
            agent.get("department_ids") or [], agent.get("role_key"), agent["member_id"])
    return [dict(r) for r in rows]



async def due_duties(limit: int = 20) -> list[dict]:
    """Live duties that are due, or that have never been given a time."""
    p = await pool()
    async with p.acquire() as con:
        rows = await con.fetch("""
            SELECT id, agent_member_id, name, instructions, schedule_cron, timezone, next_run_at
              FROM agent_duties
             WHERE active AND (next_run_at IS NULL OR next_run_at <= now())
             ORDER BY next_run_at NULLS FIRST, id LIMIT $1""", limit)
    return [dict(r) for r in rows]


async def move_duty(duty_id: int, next_run_at, ran: bool) -> None:
    p = await pool()
    async with p.acquire() as con:
        if ran:
            await con.execute("UPDATE agent_duties SET last_run_at = now(), next_run_at = $2 WHERE id = $1", duty_id, next_run_at)
        else:
            await con.execute("UPDATE agent_duties SET next_run_at = $2 WHERE id = $1", duty_id, next_run_at)


async def family(parent_run_id: int) -> dict | None:
    """The run that delegated, and everything started under it."""
    p = await pool()
    async with p.acquire() as con:
        parent = await con.fetchrow(
            "SELECT id, agent_member_id, status, instructions, parent_run_id, trigger FROM agent_runs WHERE id = $1", parent_run_id)
        if parent is None:
            return None
        members = await con.fetch("""
            SELECT r.id, r.agent_member_id, m.display_name AS agent_name, r.status, r.result, r.error, r.instructions
              FROM agent_runs r JOIN members m ON m.id = r.agent_member_id
             WHERE r.parent_run_id = $1 ORDER BY r.id""", parent_run_id)
    return {"parent": dict(parent), "members": [dict(r) for r in members]}


async def chain_depth(run_id: int) -> int:
    """How many continuations lie above this run (same agent as its parent = a continuation)."""
    p = await pool()
    async with p.acquire() as con:
        return int(await con.fetchval("""
            WITH RECURSIVE up AS (
                SELECT id, parent_run_id, agent_member_id, 0 AS depth FROM agent_runs WHERE id = $1
                UNION ALL
                SELECT r.id, r.parent_run_id, r.agent_member_id, up.depth + (r.agent_member_id = up.agent_member_id)::int
                  FROM agent_runs r JOIN up ON r.id = up.parent_run_id WHERE up.depth < 20)
            SELECT max(depth) FROM up""", run_id) or 0)


# ---- Evaluations (docs/build-specs/eval-runner.md) ---------------------------------------
# db/046 already had every column these need. An eval run is ordinary evidence: its trials are
# agent_runs with trigger='eval' and its judging is in the prompt ledger as call_kind='grader'.

EVAL_COST_CAP = Decimal("5")          # per eval run, separate from the agent's own budget (settled)


async def model_by_key(model_key: str) -> dict | None:
    p = await pool()
    async with p.acquire() as con:
        row = await con.fetchrow("SELECT * FROM model_registry WHERE model_key = $1 AND status = 'active'",
                                 model_key)
    return dict(row) if row else None


def mint_judge_key(eval_run_id: int, ttl_seconds: int = 3600) -> str:
    return run_token.mint_judge_key(eval_run_id, ttl_seconds, config.require("PROXY_KEY_SECRET", 32))


async def judge_for_proxy(eval_run_id: int, model_key: str | None = None) -> dict | None:
    """What the ledger proxy needs about a GRADING call. Shaped like run_for_proxy's answer so the
    proxy treats both the same, but with `id` None — there is no agent run behind a judge call, and
    prompt_ledger.agent_run_id is nullable for exactly this."""
    p = await pool()
    async with p.acquire() as con:
        row = await con.fetchrow("""
            SELECT er.id AS eval_run_id, er.status, er.agent_member_id, er.started_by, er.eval_set_id
              FROM eval_runs er WHERE er.id = $1""", eval_run_id)
        if row is None or row["status"] not in ("queued", "running"):
            return None
        # A route that names its model (JEV's systemone) says which; the chat routes read the binding.
        judge = await con.fetchrow("SELECT * FROM model_registry WHERE model_key = $1",
                                   model_key or _judge_key.get(eval_run_id))
        if judge is None:
            return None
    return {"id": None, "eval_run_id": row["eval_run_id"], "status": "running",
            "agent_member_id": row["agent_member_id"], "acting_member_id": row["started_by"],
            "location_id": None, "harness": "judge", "sdk_version": None,
            "request_id": f"eval-{eval_run_id}", "model_id": judge["id"], "model": dict(judge),
            "monthly_budget_amount": None, "call_kind": "grader"}


# Which model is judging which eval run. Set by the runner before it calls the judge; the proxy
# reads it to pin the model, because a judge key names the RUN, not the model.
_judge_key: dict[int, str] = {}


def set_judge_model(eval_run_id: int, model_key: str) -> None:
    _judge_key[eval_run_id] = model_key


async def eval_run_cost(eval_run_id: int, trial_run_ids: list[int] | None = None) -> Decimal:
    """Everything this evaluation has spent: its trials and its grading.

    The trial runs are passed in rather than looked up, because eval_results is written only once a
    case's three trials are OVER and keeps just the first of them — reading the cap from it would
    miss two trials in three and count nothing at all until the first case finished."""
    p = await pool()
    async with p.acquire() as con:
        return await con.fetchval("""
            SELECT COALESCE(SUM(pl.cost), 0) FROM prompt_ledger pl
             WHERE pl.request_id = $1 OR pl.agent_run_id = ANY($2::bigint[])""",
            f"eval-{eval_run_id}", trial_run_ids or [])


async def eval_run(eval_run_id: int) -> dict | None:
    """The run and what it is testing: which agent, which config version, the threshold it is
    measured against, and the model_key of the version under test (which the judge choice needs)."""
    p = await pool()
    async with p.acquire() as con:
        row = await con.fetchrow("""
            SELECT er.id, er.eval_set_id, er.agent_member_id, er.config_version_id, er.model_id,
                   er.status, er.pass_threshold, er.baseline_run_id, er.started_by, mr.model_key
              FROM eval_runs er LEFT JOIN model_registry mr ON mr.id = er.model_id
             WHERE er.id = $1""", eval_run_id)
    return dict(row) if row else None


async def eval_cases(eval_set_id: int) -> list[dict]:
    p = await pool()
    async with p.acquire() as con:
        rows = await con.fetch("""
            SELECT id, title, input, expected, rubric, grader, weight, checks FROM eval_cases
             WHERE eval_set_id = $1 AND active ORDER BY id""", eval_set_id)
    return [dict(r) for r in rows]


async def begin_eval_run(eval_run_id: int, cases_total: int) -> None:
    p = await pool()
    async with p.acquire() as con:
        await con.execute("""
            UPDATE eval_runs SET status = 'running', started_at = now(), cases_total = $2,
                                 updated_at = now() WHERE id = $1""", eval_run_id, cases_total)


async def write_eval_result(eval_run_id: int, case_id: int, agent_run_id: int | None, *, passed: bool,
                            score: float | None, notes: str, grader_model_id: int | None,
                            awaiting_person: bool = False, grader_detail: dict | None = None) -> None:
    """One row per case. Re-running a case within the same run replaces its result rather than
    adding a second (the schema's UNIQUE (eval_run_id, eval_case_id) says the same)."""
    p = await pool()
    async with p.acquire() as con:
        await con.execute("""
            INSERT INTO eval_results (eval_run_id, eval_case_id, agent_run_id, passed, score,
                                      grader_notes, grader_model_id, awaiting_person, grader_detail)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
            ON CONFLICT (eval_run_id, eval_case_id) DO UPDATE
               SET agent_run_id = EXCLUDED.agent_run_id, passed = EXCLUDED.passed, score = EXCLUDED.score,
                   grader_notes = EXCLUDED.grader_notes, grader_model_id = EXCLUDED.grader_model_id,
                   awaiting_person = EXCLUDED.awaiting_person, grader_detail = EXCLUDED.grader_detail""",
            eval_run_id, case_id, agent_run_id, passed, score, notes, grader_model_id, awaiting_person,
            json.dumps(grader_detail) if grader_detail is not None else None)


async def finish_eval_run(eval_run_id: int, *, status: str, score: float | None, passed: int,
                          total: int, detail: str, trial_run_ids: list[int] | None = None) -> None:
    """The run's own result. `detail` says what the score covers — it is appended to the set's
    own record rather than replacing anything, because a number without its caveat gets quoted."""
    p = await pool()
    async with p.acquire() as con:
        await con.execute("""
            UPDATE eval_runs
               SET status = $2, score = $3, cases_passed = $4, cases_total = GREATEST(cases_total, $5),
                   cost = (SELECT COALESCE(SUM(pl.cost), 0) FROM prompt_ledger pl
                            WHERE pl.request_id = $6 OR pl.agent_run_id = ANY($7::bigint[])),
                   finished_at = now(), updated_at = now()
             WHERE id = $1""", eval_run_id, status, score, passed, total, f"eval-{eval_run_id}",
            trial_run_ids or [])
    # `detail` is not stored: eval_runs has no column for it and inventing one would mean a
    # migration for something the screen can work out for itself from the results (how many cases
    # were graded, how many await a person). It goes to the log, where the run's history lives.
    log.info("eval run %s finished: %s", eval_run_id, detail)


async def run_row(run_id: int) -> dict | None:
    p = await pool()
    async with p.acquire() as con:
        row = await con.fetchrow("SELECT id, status, result, error FROM agent_runs WHERE id = $1", run_id)
    return dict(row) if row else None


async def eval_case_diff(eval_run_id: int, baseline_run_id: int) -> list[dict]:
    """Which cases changed between two runs of the same set."""
    p = await pool()
    async with p.acquire() as con:
        rows = await con.fetch("""
            SELECT c.id AS eval_case_id, c.title,
                   b.passed AS was, n.passed AS now_passed
              FROM eval_results n
              JOIN eval_cases c ON c.id = n.eval_case_id
              LEFT JOIN eval_results b ON b.eval_case_id = n.eval_case_id AND b.eval_run_id = $2
             WHERE n.eval_run_id = $1 AND b.passed IS DISTINCT FROM n.passed
             ORDER BY n.passed, c.id""", eval_run_id, baseline_run_id)
    return [dict(r) for r in rows]


async def run_changed_anything(run_id: int) -> list[str]:
    """What this run actually CHANGED, from the activity log. Screen views and the log's own
    bookkeeping are not changes; everything else is.

    Used as the eval runner's own check on the rule it depends on but does not implement. Eval
    run 1 created two real tasks because the actions server never set the run id, so the write
    interception never saw an evaluation. The rule now holds in two independent places: the
    interception at the MCP boundary, and this — which would have caught that failure on the
    first trial instead of the fifth.
    """
    p = await pool()
    async with p.acquire() as con:
        # One narrow SECURITY DEFINER function (db/125), not the activity log: db/097's rule is
        # that the runner reads no business records, and one fact about one run is all this needs.
        rows = await con.fetch("SELECT action FROM run_changed_anything($1)", run_id)
    return [r["action"] for r in rows]


# ---- messages (db/155) --------------------------------------------------------------------------------

async def agents_with_waiting_messages(settle_seconds: int = 20) -> list[int]:
    """Agents with unread messages no run has taken yet, ready to wake: the newest waited `settle_seconds`
    (so a burst becomes one run), or one of them is urgent or from the agent's own person."""
    p = await pool()
    async with p.acquire() as con:
        rows = await con.fetch("""
            SELECT m.to_member_id
              FROM agent_messages m
              JOIN members r ON r.id = m.to_member_id AND r.member_kind = 'agent' AND r.status = 'active'
              JOIN agent_profiles ap ON ap.member_id = m.to_member_id AND ap.status = 'active'
             WHERE m.status = 'unread' AND m.woke_run_id IS NULL
             GROUP BY m.to_member_id, ap.principal_member_id
            HAVING max(m.created_at) <= now() - make_interval(secs => $1)
                OR bool_or(m.priority = 'urgent')
                OR bool_or(m.from_member_id = ap.principal_member_id)
             ORDER BY min(m.created_at)
             LIMIT 20""", settle_seconds)
    return [int(r["to_member_id"]) for r in rows]


async def waiting_messages(agent_member_id: int, limit: int = 20) -> list[dict]:
    """The unread messages no run has taken yet, oldest first, with who sent them."""
    p = await pool()
    async with p.acquire() as con:
        rows = await con.fetch("""
            SELECT m.id, m.thread_id, t.subject AS thread_subject, m.kind, m.priority, m.subject, m.body, m.channel,
                   m.created_at, m.from_member_id, f.display_name AS from_name, f.member_kind AS from_kind,
                   (ap.principal_member_id = m.from_member_id) AS from_my_person
              FROM agent_messages m
              JOIN agent_message_threads t ON t.id = m.thread_id
              JOIN members f ON f.id = m.from_member_id
              JOIN agent_profiles ap ON ap.member_id = m.to_member_id
             WHERE m.to_member_id = $1 AND m.status = 'unread' AND m.woke_run_id IS NULL
             ORDER BY m.created_at LIMIT $2""", agent_member_id, limit)
    return [dict(r) for r in rows]


async def mark_messages_woken(message_ids: list[int], run_id: int) -> None:
    """The run that carries these messages has them: read, and never woken again."""
    p = await pool()
    async with p.acquire() as con:
        await con.execute("""
            UPDATE agent_messages SET woke_run_id = $2, status = 'read', read_at = now()
             WHERE id = ANY($1::bigint[]) AND woke_run_id IS NULL""", message_ids, run_id)
