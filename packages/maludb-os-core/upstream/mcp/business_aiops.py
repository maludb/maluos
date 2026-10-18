"""AI Ops — read tools (docs/business-os-mcp-tool-surface.md "Prompt ledger & runtime" and
"Evaluations"; docs/build-specs/ai-ops.md). `agent_runs`, `ledger_calls` and
`prompt_for_request` already live in business_agents.py; these are the rest.

Reads: mcp_prompt_ledger, mcp_model_registry, mcp_ai_usage_postings, mcp_ai_periods, mcp_eval_sets,
mcp_eval_runs, mcp_eval_results, mcp_eval_cases, mcp_eval_schedules, mcp_eval_alerts,
mcp_trace_grades, mcp_agent_config_versions. Every query runs as the asking member, so the views
decide: the `ledger` grant, one's own calls, the agents one may see; eval CASES are humans-only
in the view itself. No tool here returns a prompt payload.

**There is no eval runner yet** (owner's decision, 2026-09-19). The eval tools therefore say so
in their answer — an empty list of alerts or runs must never read as "all is well".
"""
from __future__ import annotations

import datetime
import json

from pydantic import Field

from business_common import RO, _Base, _iso_date, _period_bounds

_PERIODS = "'today', 'this_week', 'last_week', 'this_month', 'last_month', 'this_quarter', 'last_quarter', 'ytd', 'last_12_months'"
# The runner exists since 2026-09-20 (docs/build-specs/eval-runner.md). What is still true, and
# matters more, is that evals ADVISE: a run happens because a person asked for one, nothing is
# scheduled, nothing is gated, and no alert is raised. So an empty answer still means nobody has
# looked — which is the thing a reader must never mistake for "everything passed".
_ON_DEMAND = ("Evaluations are run on demand by a person and advise only: nothing here is scheduled, nothing "
              "blocks an activation, and no alert is raised. An empty answer means nobody has evaluated this "
              "— not that it passed.")


class AiSpendIn(_Base):
    period: str | None = Field("this_month", description=f"{_PERIODS}. Any other word is read as this_month")
    date_from: str | None = Field(None, description="ISO date; overrides period")
    date_to: str | None = Field(None, description="ISO date; overrides period")
    group_by: str = Field("agent", description="'agent', 'model', 'provider', 'location', 'department' or 'day'")
    agent_member_id: int | None = Field(None, description="Only this agent's calls")
    view: str = Field("usage", description="'usage' (default: cost, tokens, latency, cache savings) or 'statements' (the period statements, per month)")


class LedgerPeriodIn(_Base):
    period: str | None = Field(None, description="'YYYY-MM'. Omit for the list of months and whether each is open or closed")


class ModelCatalogIn(_Base):
    status: str | None = Field(None, description="'active' (default when omitted: every status), 'deprecated', 'disabled' …")


class EvalStatusIn(_Base):
    agent_member_id: int | None = Field(None, description="Only this agent's eval runs")
    eval_set_id: int | None = Field(None, description="Only this eval set")
    trigger: str | None = Field(None, description="'hiring', 'change_control', 'continuous' or 'manual'")
    compare_to_baseline: bool = Field(False, description="Also return each run's baseline run and the score difference")


class EvalFindingsIn(_Base):
    view: str = Field("failing_cases", description="'failing_cases', 'promoted' (cases made from real traces, with their source), 'graded_traces', or 'jev' (JEV-graded results: each check's outcome, value and confidence per trial; include awaiting ones)")
    eval_run_id: int | None = Field(None, description="view 'jev': only this eval run")
    period: str | None = Field(None, description=f"{_PERIODS}; omit for all time")
    agent_member_id: int | None = Field(None, description="Only this agent")


class SystemEventsIn(_Base):
    status: str | None = Field(None, description="'open' (open and acknowledged — the default), 'muted', 'resolved' or 'all'")
    category: str | None = Field(None, description="bug, outage, security, guardrail, performance or noise")
    min_severity: int | None = Field(None, description="0 (noise) to 4 (critical)")
    source: str | None = Field(None, description="Where from, e.g. 'apache', 'journal', 'postgresql', 'guardrail' (a prefix)")
    period: str | None = Field(None, description=f"{_PERIODS}; by when last seen; omit for all time")


class SystemHealthIn(_Base):
    only_problems: bool = Field(False, description="Only probes that are failed or warning")


class AuditFindingsIn(_Base):
    period: str | None = Field(None, description=f"{_PERIODS}; omit for the last 30 days")
    agent_member_id: int | None = Field(None, description="Only findings about this audited agent's work")


class SystemOneDecisionsIn(_Base):
    agent_member_id: int | None = Field(None, description="Only this system_one agent (the Auditor, the Sysadmin)")
    playbook: str | None = Field(None, description="scheduled_evals, trace_sampling, evidence_integrity, health or logs_and_guardrails")
    decision: str | None = Field(None, description="record, finding, alert, escalate or mute; omit for everything but record")
    mode: str | None = Field(None, description="'shadow' (what it would have done) or 'live'")
    period: str | None = Field(None, description=f"{_PERIODS}; omit for the last 7 days")


class EvalCalibrationIn(_Base):
    eval_set_id: int = Field(..., description="The eval set whose JEV checks to look at")


class EvalWatchIn(_Base):
    agent_member_id: int | None = Field(None, description="Only this agent (an agent asking about itself may omit it)")
    status: str | None = Field(None, description="'open', 'acknowledged' or 'resolved'; omit for open and acknowledged")
    severity: str | None = Field(None, description="'info', 'warning' or 'critical'")


class UngatedIn(_Base):
    period: str | None = Field(None, description=f"{_PERIODS}; omit for all time")


class RunVerdictsIn(_Base):
    agent_member_id: int | None = Field(None, description="Only runs by this agent")
    verdict: str | None = Field(None, description="'good' or 'bad'; omit for both")
    subject: str | None = Field(None, description="'run' for agent runs, 'call' for assistant answers; omit for both")
    period: str | None = Field(None, description=f"{_PERIODS}; omit for all time")
    limit: int = Field(100, ge=1, le=500)


def register(mcp, q) -> None:
    @mcp.tool(name="ai_spend", annotations={"title": "AI spend", **RO})
    async def ai_spend(params: AiSpendIn) -> str:
        """What the models cost: calls, failures, tokens, average latency, cost and what prompt
        caching saved — grouped by agent, model, provider, location, department or day; or
        (view='statements') the period statements the ledger exports, per month. Call for "what
        did AI cost this month", "which agent costs the most", "how much does caching save",
        "what did we hand the accountant for August". You see the calls you may see: everything
        with the AI ops grant, otherwise your own and your agents'. Never returns a prompt."""
        if params.view == "statements":
            return await q("""SELECT ai_usage_posting_id, to_char(period_start, 'YYYY-MM') AS period, provider, model_name, department_name, agent_name, application_name,
                                     call_count, late_calls, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, amount, currency, status, closed_at, note
                                FROM mcp_ai_usage_postings ORDER BY period_start DESC, provider LIMIT 200""")
        group = params.group_by if params.group_by in ("agent", "model", "provider", "location", "department", "day") else "agent"
        key, label, join = {
            "agent": ("coalesce(pl.agent_member_id, pl.acting_member_id)", "coalesce(td.display_name, 'Someone')",
                      "LEFT JOIN mcp_team_directory td ON td.member_id = coalesce(pl.agent_member_id, pl.acting_member_id)"),
            "model": ("pl.model_id", "coalesce(mr.display_name, pl.provider_model_id)", ""),
            "provider": ("pl.provider", "pl.provider", ""),
            "location": ("pl.location_id", "coalesce((SELECT l.name FROM mcp_locations l WHERE l.location_id = pl.location_id), 'No location')", ""),
            "department": ("coalesce(td.departments[1], '')", "coalesce(td.departments[1], 'No department')",
                           "LEFT JOIN mcp_team_directory td ON td.member_id = coalesce(pl.agent_member_id, pl.acting_member_id)"),
            "day": ("(pl.occurred_at AT TIME ZONE 'UTC')::date", "(pl.occurred_at AT TIME ZONE 'UTC')::date::text", ""),
        }[group]
        where, args = ["1 = 1"], []
        bounds = _period_bounds(params.period, _iso_date(params.date_from), _iso_date(params.date_to))
        if bounds:
            where.append(f"pl.occurred_at >= ({bounds[0]}) AND pl.occurred_at < ({bounds[1]})")
        if params.agent_member_id is not None:
            args.append(params.agent_member_id); where.append(f"pl.agent_member_id = ${len(args)}")
        return await q(
            f"""
            SELECT {key} AS group_id, {label} AS label, count(*) AS calls, count(*) FILTER (WHERE pl.status <> 'ok') AS failed,
                   sum(pl.input_tokens) AS input_tokens, sum(pl.output_tokens) AS output_tokens,
                   sum(pl.cache_read_tokens) AS cache_read_tokens, sum(pl.cache_write_tokens) AS cache_write_tokens,
                   round(avg(pl.latency_ms)) AS avg_latency_ms, round(sum(pl.cost), 6) AS cost, min(pl.currency) AS currency,
                   round(coalesce(sum(pl.cache_read_tokens * (mr.price_input_per_mtok - mr.price_cache_read_per_mtok) / 1000000.0), 0), 4) AS cache_saving
              FROM mcp_prompt_ledger pl LEFT JOIN mcp_model_registry mr ON mr.model_id = pl.model_id {join}
             WHERE {' AND '.join(where)}
             GROUP BY 1, 2 ORDER BY {'1' if group == 'day' else 'sum(pl.cost) DESC'} LIMIT 200
            """, *args)

    @mcp.tool(name="ledger_period", annotations={"title": "Ledger period statement", **RO})
    async def ledger_period(params: LedgerPeriodIn) -> str:
        """The period statement the kernel exports to the accounting system (schema os.ledger-period/1):
        one month's lines per provider, model, department, agent, application and currency, with
        totals per currency, whether the month is open or closed and when it was rolled up; or,
        with no period, every month and its status. Call for "what did the agents cost in August",
        "is last month's AI statement closed", "what do we hand the accountant". Needs the AI ops
        grant. Late calls — dated in a closed month, arrived after — are counted in the open month
        and flagged."""
        if params.period is None:
            return await q("""SELECT period, period_start, period_end, status, closed_at, closed_by_name, rolled_up_at, note,
                                     (SELECT count(*) FROM mcp_ai_usage_postings s WHERE s.period_start = p.period_start AND s.status <> 'void') AS statement_lines
                                FROM mcp_ai_periods p ORDER BY period_start DESC LIMIT 36""")
        if len(params.period) != 7 or params.period[4] != "-" or not (params.period[:4] + params.period[5:]).isdigit():
            return json.dumps({"status": "error", "message": "period is written YYYY-MM"})
        start = datetime.date.fromisoformat(params.period + "-01")
        return await q("""
            SELECT 'os.ledger-period/1' AS schema, $1::text AS period,
                   (SELECT to_jsonb(p) FROM mcp_ai_periods p WHERE p.period_start = $2::date) AS period_status,
                   COALESCE((SELECT jsonb_agg(jsonb_build_object(
                                'provider', s.provider, 'model', s.model_name, 'department', s.department_name, 'agent', s.agent_name,
                                'application', s.application_name, 'calls', s.call_count, 'late_calls', s.late_calls,
                                'input_tokens', s.input_tokens, 'output_tokens', s.output_tokens,
                                'cache_read_tokens', s.cache_read_tokens, 'cache_write_tokens', s.cache_write_tokens,
                                'amount', s.amount, 'currency', s.currency, 'note', s.note)
                             ORDER BY s.provider, s.model_name, s.department_name, s.agent_name)
                       FROM mcp_ai_usage_postings s WHERE s.period_start = $2::date AND s.status <> 'void'), '[]') AS lines,
                   COALESCE((SELECT jsonb_agg(jsonb_build_object('currency', t.currency, 'calls', t.calls, 'late_calls', t.late_calls,
                                'input_tokens', t.input_tokens, 'output_tokens', t.output_tokens, 'amount', t.amount))
                       FROM (SELECT currency, sum(call_count) AS calls, sum(late_calls) AS late_calls, sum(input_tokens) AS input_tokens,
                                    sum(output_tokens) AS output_tokens, sum(amount) AS amount
                               FROM mcp_ai_usage_postings WHERE period_start = $2::date AND status <> 'void' GROUP BY currency) t), '[]') AS totals
            """, params.period, start)

    @mcp.tool(name="model_catalog", annotations={"title": "Model catalogue", **RO})
    async def model_catalog(params: ModelCatalogIn) -> str:
        """Which models are registered, the harness each runs on, its context window and its
        prices per million tokens (input, output, cache read, cache write). Call for "which
        models can we use", "what does Sonnet cost", "which harness runs GPT". No API key is in
        the registry view."""
        args: list = []
        where = ""
        if params.status:
            args.append(params.status); where = "WHERE status = $1"
        return await q(f"""SELECT model_id, model_key, display_name, provider, provider_model_id, harness, context_window_tokens,
                                  price_input_per_mtok, price_output_per_mtok, price_cache_read_per_mtok, price_cache_write_per_mtok, currency, status
                             FROM mcp_model_registry {where} ORDER BY provider, display_name""", *args)

    @mcp.tool(name="eval_status", annotations={"title": "Eval status", **RO})
    async def eval_status(params: EvalStatusIn) -> str:
        """Eval runs and their scores: did a candidate pass its hiring evals, an agent's score
        over time, whether the last change regressed against its baseline. People only. NOTE:
        there is no eval runner yet, so there are no runs — the answer says so and lists the
        sets that exist, so "no runs" is never mistaken for "passed"."""
        where, args = ["1 = 1"], []
        for column, value in (("agent_member_id", params.agent_member_id), ("eval_set_id", params.eval_set_id), ("trigger", params.trigger)):
            if value is not None:
                args.append(value); where.append(f"r.{column} = ${len(args)}")
        baseline = (", r.baseline_run_id, (SELECT b.score FROM mcp_eval_runs b WHERE b.eval_run_id = r.baseline_run_id) AS baseline_score, "
                    "r.score - (SELECT b.score FROM mcp_eval_runs b WHERE b.eval_run_id = r.baseline_run_id) AS change") if params.compare_to_baseline else ""
        runs = json.loads(await q(
            f"""SELECT r.eval_run_id, r.eval_set_id, r.eval_set_name, r.agent_member_id, r.config_version_id, r.trigger, r.status, r.score,
                       r.pass_threshold, r.cases_total, r.cases_passed, r.cost, r.currency, r.started_at, r.finished_at{baseline},
                       (SELECT count(*) FROM mcp_eval_results x WHERE x.eval_run_id = r.eval_run_id AND NOT x.is_graded) AS awaiting_person
                  FROM mcp_eval_runs r WHERE {' AND '.join(where)} ORDER BY r.created_at DESC LIMIT 100""", *args))
        sets = json.loads(await q(
            """SELECT s.eval_set_id, s.name, s.agent_member_id, s.role_key, s.pass_threshold, s.status,
                      (SELECT count(*) FROM mcp_eval_cases c WHERE c.eval_set_id = s.eval_set_id AND c.active) AS active_cases
                 FROM mcp_eval_sets s WHERE ($1::bigint IS NULL OR s.agent_member_id = $1) AND ($2::bigint IS NULL OR s.eval_set_id = $2) ORDER BY s.name LIMIT 100""",
            params.agent_member_id, params.eval_set_id))
        return json.dumps({"runner_built": True, "note": _ON_DEMAND, "runs": runs, "eval_sets": sets}, default=str)

    @mcp.tool(name="eval_findings", annotations={"title": "Eval findings", **RO})
    async def eval_findings(params: EvalFindingsIn) -> str:
        """What the evals found: the cases that fail most (failing_cases), the cases made from
        real traces and where each came from (promoted), or production runs that graded poorly
        (graded_traces). People only — an agent never sees eval cases. No eval runner exists
        yet, so failing_cases and graded_traces are empty for that reason; promoted is real."""
        bounds = _period_bounds(params.period, None, None) if params.period else None
        args: list = []
        agent = ""
        if params.view == "promoted":
            if params.agent_member_id is not None:
                args.append(params.agent_member_id); agent = f"AND s.agent_member_id = ${len(args)}"
            when = f"AND c.created_at >= ({bounds[0]}) AND c.created_at < ({bounds[1]})" if bounds else ""
            rows = await q(f"""SELECT c.eval_case_id, c.title, c.eval_set_id, s.name AS eval_set_name, c.source_ledger_id, c.source_run_id, c.promoted_by, c.active, c.created_at
                                 FROM mcp_eval_cases c JOIN mcp_eval_sets s ON s.eval_set_id = c.eval_set_id
                                WHERE c.origin = 'promoted_trace' {agent} {when} ORDER BY c.created_at DESC LIMIT 100""", *args)
        elif params.view == "jev":
            if params.eval_run_id is not None:
                args.append(params.eval_run_id); agent = f"AND r.eval_run_id = ${len(args)}"
            elif params.agent_member_id is not None:
                args.append(params.agent_member_id); agent = f"AND run.agent_member_id = ${len(args)}"
            when = f"AND r.created_at >= ({bounds[0]}) AND r.created_at < ({bounds[1]})" if bounds else ""
            rows = await q(f"""SELECT r.eval_result_id, r.eval_run_id, r.eval_case_id, r.case_title, r.passed, r.score, r.is_graded,
                                      r.awaiting_person, r.graded_by IS NOT NULL AS graded_by_person,
                                      r.grader_detail->>'verdict' AS jev_verdict,
                                      (SELECT jsonb_agg(jsonb_build_object('trial', t.ord, 'verdict', t.trial->'verdict', 'guard', t.trial->'guard',
                                                 'checks', (SELECT jsonb_object_agg(k, jsonb_build_object('outcome', v->'outcome', 'value', v->'value',
                                                                'choice', v->'choice', 'level', v->'level', 'confidence', v->'confidence'))
                                                              FROM jsonb_each(t.trial->'checks') AS e(k, v))))
                                         FROM jsonb_array_elements(r.grader_detail->'trials') WITH ORDINALITY AS t(trial, ord)) AS trials
                                 FROM mcp_eval_results r JOIN mcp_eval_runs run ON run.eval_run_id = r.eval_run_id
                                WHERE r.grader = 'jev' {agent} {when} ORDER BY r.eval_result_id DESC LIMIT 50""", *args)
        elif params.view == "graded_traces":
            if params.agent_member_id is not None:
                args.append(params.agent_member_id); agent = f"AND g.agent_member_id = ${len(args)}"
            when = f"AND g.graded_at >= ({bounds[0]}) AND g.graded_at < ({bounds[1]})" if bounds else ""
            rows = await q(f"""SELECT g.trace_grade_id, g.agent_run_id, g.agent_member_id, g.eval_set_id, g.score, g.passed, left(g.grader_notes, 500) AS grader_notes, g.graded_at
                                 FROM mcp_trace_grades g WHERE g.passed = false {agent} {when} ORDER BY g.graded_at DESC NULLS LAST LIMIT 100""", *args)
        else:
            if params.agent_member_id is not None:
                args.append(params.agent_member_id); agent = f"AND run.agent_member_id = ${len(args)}"
            when = f"AND r.created_at >= ({bounds[0]}) AND r.created_at < ({bounds[1]})" if bounds else ""
            rows = await q(f"""SELECT r.eval_case_id, r.case_title, count(*) AS times_run, count(*) FILTER (WHERE NOT r.passed) AS times_failed,
                                      round(100.0 * count(*) FILTER (WHERE NOT r.passed) / count(*)) AS fail_rate_pct
                                 FROM mcp_eval_results r JOIN mcp_eval_runs run ON run.eval_run_id = r.eval_run_id
                                WHERE 1 = 1 {agent} {when} GROUP BY 1, 2 HAVING count(*) FILTER (WHERE NOT r.passed) > 0 ORDER BY 4 DESC LIMIT 50""", *args)
        return json.dumps({"runner_built": True, "note": _ON_DEMAND, "view": params.view, "rows": json.loads(rows)}, default=str)

    @mcp.tool(name="eval_calibration", annotations={"title": "Eval calibration", **RO})
    async def eval_calibration(params: EvalCalibrationIn) -> str:
        """How far JEV's checks can be trusted in one eval set (db/144): for each check, how often it
        passed, failed or was unsure across every trial it graded, its mean confidence, and — where a
        person graded the same result — how often the check's confident outcome agreed with them. A
        check people often disagree with needs rewording or a different threshold; one that is often
        unsure sends many cases to people. People only. Call for "can we trust the cites_policy check",
        "which checks send most cases to a person"."""
        rows = json.loads(await q(
            """SELECT check_id, answers, passes, fails, uncertain, person_graded, person_agreed, mean_confidence,
                      CASE WHEN person_graded > 0 THEN round(100.0 * person_agreed / person_graded, 1) END AS agreement_pct
                 FROM mcp_eval_check_calibration WHERE eval_set_id = $1 ORDER BY check_id""", params.eval_set_id))
        return json.dumps({"eval_set_id": params.eval_set_id, "checks": rows,
                           "note": "Agreement counts only results a person graded; TypeSafe's thresholds are examples — "
                                   "tune pass_at, the uncertain band and min_confidence on these numbers."}, default=str)

    # ---- the system_one agents (db/145) ------------------------------------------------------------------
    @mcp.tool(name="system_events", annotations={"title": "System events", **RO})
    async def system_events(params: SystemEventsIn) -> str:
        """What is going wrong on the server, as the Sysadmin sees it: events from the service journals,
        the Apache and PostgreSQL logs and the kernel's guardrails (refusals, withheld instructions, failed
        sign-ins), each grouped by kind, classified by JEV (category, severity 0-4) and REDACTED — no raw log
        line, token or address is ever here. The super-admin and IT admins. Call for "anything wrong on the
        server", "any security events today", "what's new in the logs"."""
        where, args = ["1 = 1"], []
        st = params.status or "open"
        if st == "open":
            where.append("e.status IN ('open', 'acknowledged')")
        elif st in ("muted", "resolved"):
            args.append(st); where.append(f"e.status = ${len(args)}")
        if params.category:
            args.append(params.category); where.append(f"e.category = ${len(args)}")
        if params.min_severity is not None:
            args.append(params.min_severity); where.append(f"e.severity >= ${len(args)}")
        if params.source:
            args.append(params.source + "%"); where.append(f"e.source LIKE ${len(args)}")
        if params.period:
            b = _period_bounds(params.period, None, None)
            where.append(f"e.last_seen >= ({b[0]}) AND e.last_seen < ({b[1]})")
        return await q(f"""SELECT e.system_event_id, e.source, e.sample, e.category, e.severity, e.occurrences, e.first_seen,
                                  e.last_seen, e.status, e.status_by_name, e.note
                             FROM mcp_system_events e WHERE {' AND '.join(where)}
                            ORDER BY e.severity DESC NULLS LAST, e.last_seen DESC LIMIT 100""", *args)

    @mcp.tool(name="system_health", annotations={"title": "System health", **RO})
    async def system_health(params: SystemHealthIn) -> str:
        """The server's health as the Sysadmin last probed it: every platform and application service, disk,
        memory and swap, the last good backup, each application's health endpoint and version — with when
        each was checked and when its status last changed. Call for "are all services up", "how is the
        disk", "when was the last backup", "is HR healthy"."""
        extra = "WHERE status <> 'ok'" if params.only_problems else ""
        return await q(f"""SELECT probe, status, detail, checked_at, changed_at FROM mcp_system_probes {extra}
                           ORDER BY CASE status WHEN 'failed' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, probe""")

    @mcp.tool(name="audit_findings", annotations={"title": "Audit findings", **RO})
    async def audit_findings(params: AuditFindingsIn) -> str:
        """What the Auditor found about agents' work: regressions and runs below their pass mark, real runs
        JEV failed or was unsure of, and gaps in the audit trail (a run with no ledger row, an evaluation that
        changed something) — with the open eval alerts. In shadow mode these are what it WOULD have raised.
        Findings advise; a person decides. Call for "what did the auditor find this week", "which agents
        regressed", "is the audit trail complete"."""
        if params.period:
            b = _period_bounds(params.period, None, None)
            when = f"d.created_at >= ({b[0]}) AND d.created_at < ({b[1]})"
        else:
            when = "d.created_at >= now() - interval '30 days'"
        findings = await q(f"""SELECT d.decision_id, d.agent_name AS auditor, d.playbook, d.subject_kind, d.subject_id, d.subject_label,
                                      d.decision, d.mode, d.acted, d.note, d.created_at
                                 FROM mcp_system_one_decisions d
                                WHERE d.playbook IN ('scheduled_evals', 'trace_sampling', 'evidence_integrity')
                                  AND d.decision <> 'record' AND {when}
                                ORDER BY d.created_at DESC LIMIT 100""")
        args: list = []
        agent = ""
        if params.agent_member_id is not None:
            args.append(params.agent_member_id); agent = f"AND a.agent_member_id = ${len(args)}"
        alerts = await q(f"""SELECT a.eval_alert_id, a.eval_set_name, a.agent_name, a.kind, a.severity, a.score, a.baseline_score,
                                    a.detail, a.status, a.opened_at
                               FROM mcp_eval_alerts a WHERE a.status <> 'resolved' {agent} ORDER BY a.opened_at DESC LIMIT 50""", *args)
        return '{"findings": ' + findings + ', "open_eval_alerts": ' + alerts + '}'

    @mcp.tool(name="system_one_decisions", annotations={"title": "System One decisions", **RO})
    async def system_one_decisions(params: SystemOneDecisionsIn) -> str:
        """The decision trail of the system_one agents (the Auditor, the Sysadmin): each item judged, what
        JEV answered, what was decided (record, finding, alert, escalate, mute), whether it was acted on, and
        the mode — in shadow nothing was sent, so this is what it WOULD have done. Call for "what would the
        sysadmin have alerted on", "why was this muted", "is the auditor ready to go live"."""
        where, args = ["1 = 1"], []
        if params.agent_member_id is not None:
            args.append(params.agent_member_id); where.append(f"d.agent_member_id = ${len(args)}")
        if params.playbook:
            args.append(params.playbook); where.append(f"d.playbook = ${len(args)}")
        if params.decision:
            args.append(params.decision); where.append(f"d.decision = ${len(args)}")
        else:
            where.append("d.decision <> 'record'")
        if params.mode in ("shadow", "live"):
            args.append(params.mode); where.append(f"d.mode = ${len(args)}")
        if params.period:
            b = _period_bounds(params.period, None, None)
            where.append(f"d.created_at >= ({b[0]}) AND d.created_at < ({b[1]})")
        else:
            where.append("d.created_at >= now() - interval '7 days'")
        return await q(f"""SELECT d.decision_id, d.agent_name, d.playbook, d.subject_kind, d.subject_id, d.subject_label, d.answers,
                                  d.decision, d.mode, d.acted, d.note, d.created_at
                             FROM mcp_system_one_decisions d WHERE {' AND '.join(where)} ORDER BY d.created_at DESC LIMIT 100""", *args)

    @mcp.tool(name="eval_watch", annotations={"title": "Eval watch", **RO})
    async def eval_watch(params: EvalWatchIn) -> str:
        """The Audit department's standing watch: which eval sets are on a schedule and when
        each runs next, and the degradation alerts that are open — threshold breaches,
        regressions against baseline, trace drift, missed cycles. An agent may call it to see
        its own alerts. IMPORTANT: no eval runner exists yet, so nothing raises alerts and no
        schedule has a next run — the answer states that, so "no alerts" is not read as "no
        degradation"."""
        where, args = ["1 = 1"], []
        if params.agent_member_id is not None:
            args.append(params.agent_member_id); where.append(f"a.agent_member_id = ${len(args)}")
        if params.status in ("open", "acknowledged", "resolved"):
            args.append(params.status); where.append(f"a.status = ${len(args)}")
        else:
            where.append("a.status <> 'resolved'")
        if params.severity in ("info", "warning", "critical"):
            args.append(params.severity); where.append(f"a.severity = ${len(args)}")
        alerts = json.loads(await q(
            f"""SELECT a.eval_alert_id, a.eval_set_name, a.agent_member_id, a.agent_name, a.kind, a.severity, a.score, a.baseline_score, a.detail, a.status, a.opened_at, a.acknowledged_at
                  FROM mcp_eval_alerts a WHERE {' AND '.join(where)} ORDER BY a.opened_at DESC LIMIT 100""", *args))
        schedules = json.loads(await q(
            """SELECT h.eval_schedule_id, h.eval_set_id, h.eval_set_name, h.agent_member_id, h.kind, h.cadence, h.sample_size, h.regression_delta, h.active, h.next_run_at, h.last_run_at
                 FROM mcp_eval_schedules h WHERE ($1::bigint IS NULL OR h.agent_member_id = $1) ORDER BY h.eval_set_name LIMIT 100""", params.agent_member_id))
        return json.dumps({"runner_built": True, "note": _ON_DEMAND, "alerts": alerts, "schedules": schedules}, default=str)

    @mcp.tool(name="ungated_deployments", annotations={"title": "Ungated deployments", **RO})
    async def ungated_deployments(params: UngatedIn) -> str:
        """Audit: agent configuration versions that went live WITHOUT a passing eval run behind
        them. The healthy answer is none — but today every activation is ungated by
        necessity, because no eval runner exists (and a hire's version 1 is exempt by decision,
        db/096); the answer says so. Super-admin's view of mcp_agent_config_versions."""
        bounds = _period_bounds(params.period, None, None) if params.period else None
        when = f"AND v.activated_at >= ({bounds[0]}) AND v.activated_at < ({bounds[1]})" if bounds else ""
        rows = json.loads(await q(
            f"""SELECT v.config_version_id, v.agent_member_id, v.version_no, v.change_note, v.activated_at, v.activated_by,
                       (v.version_no = 1) AS exempt_first_version
                  FROM mcp_agent_config_versions v
                 WHERE app_is_super_admin() AND v.activated_at IS NOT NULL {when}   -- gate: super (tool surface)
                   AND (v.gating_eval_run_id IS NULL
                        OR NOT EXISTS (SELECT 1 FROM mcp_eval_runs r WHERE r.eval_run_id = v.gating_eval_run_id AND r.status = 'passed'))
                 ORDER BY v.activated_at DESC LIMIT 100"""))
        return json.dumps({"runner_built": True, "note": _ON_DEMAND + " Version 1 of a hire goes live without an eval by decision (db/096).", "versions": rows}, default=str)

    @mcp.tool(name="run_verdicts", annotations={"title": "What people thought of the work", **RO})
    async def run_verdicts(params: RunVerdictsIn) -> str:
        """What PEOPLE said about agent runs and assistant answers — the human good/bad labels
        from db/124, with their notes. Call this for "which of Becky's runs were marked bad?",
        "what did people complain about last week?", or to gather candidates for eval cases before
        an eval run. These are judgements a person typed, not scores anything computed: an empty
        answer means nobody has said, NOT that the work was good. Not for cost or tokens
        (`ai_spend`) and not for what a run did (`agent_timeline`)."""
        where, args = ["1 = 1"], []
        if params.agent_member_id is not None:
            args.append(params.agent_member_id)
            where.append(f"(r.agent_member_id = ${len(args)} OR pl.agent_member_id = ${len(args)})")
        if params.verdict in ("good", "bad"):
            args.append(params.verdict); where.append(f"v.verdict = ${len(args)}")
        if params.subject == "run":
            where.append("v.agent_run_id IS NOT NULL")
        elif params.subject == "call":
            where.append("v.prompt_ledger_id IS NOT NULL")
        bounds = _period_bounds(params.period, None, None) if params.period else None
        if bounds:
            where.append(f"v.updated_at >= ({bounds[0]}) AND v.updated_at < ({bounds[1]})")
        args.append(params.limit)
        rows = json.loads(await q(
            f"""SELECT v.run_verdict_id, v.verdict, v.note, v.member_name, v.updated_at,
                       v.agent_run_id, v.prompt_ledger_id,
                       r.agent_name,
                       COALESCE(r.agent_member_id, pl.agent_member_id) AS agent_member_id,
                       r.trigger, r.status AS run_status
                  FROM mcp_run_verdicts v
                  LEFT JOIN mcp_agent_runs r ON r.agent_run_id = v.agent_run_id
                  LEFT JOIN mcp_prompt_ledger pl ON pl.ledger_id = v.prompt_ledger_id
                 WHERE {' AND '.join(where)}
                 ORDER BY v.updated_at DESC LIMIT ${len(args)}""", *args))
        counts = {"good": sum(1 for r in rows if r["verdict"] == "good"),
                  "bad": sum(1 for r in rows if r["verdict"] == "bad")}
        return json.dumps({
            "note": "A verdict is one person's judgement. Nothing is scored automatically, and no "
                    "verdict at all is the commonest case — silence is not approval.",
            "counts": counts, "verdicts": rows}, default=str)
