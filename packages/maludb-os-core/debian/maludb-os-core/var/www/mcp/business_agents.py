"""Agent HR tools for the record-memory server (build spec: docs/build-specs/agent-hr.md).

Three tools — exactly the "Departments & agent HR" rows docs/business-os-mcp-tool-surface.md
assigns to views this slice actually builds: `find_agents`, `agent_profile`, `hr_history`.
`agent_performance` waited for the agent runner (docs/build-specs/agent-runtime-hermes.md): it
reads mcp_agent_runs, which held no row until an agent could run. Eval scores come back as an
empty list until the evals runner exists — a real answer ("never evaluated"), not a stub.

Every tool reads mcp_* views only, so the rows a person gets and the rows their agent gets are
decided by the same app_can_see_agent() in SQL — an insider sees who works here (mcp_agents is
insider-open); job description, tool grants, schedule, config history and events go through
app_can_see_agent() (hr grant holder, the agent's own manager, or the agent itself), so a plain
insider calling agent_profile on someone else's agent simply gets less back, never an error.

db/070 (agent identity + prompt library) added agent_profiles.description/role_key; db/090
replaced the external picture URL with a held file, and mcp_agents.profile_pic_url is now the
address that serves it (or NULL)
and agent_config_versions.system_prompt_id/system_prompt_version, but did not extend mcp_agents
or mcp_agent_config_versions to carry them (this follow-up pass may not touch db/). Both queries
below join back to the base table on the primary key of a row the mcp_* view already decided this
caller may see — never a new row, just extra columns on one already authorized — the same move
find_agent()/find_agent_version() make in app/features/agents/queries.php on the PHP side.
config_versions.harness_config already carries the resolved model parameters for a cited prompt
version (db/071's mirror trigger), via the view, so no extra join is needed for those.

Registered by records_server.py; the module never opens its own connection.
"""
from __future__ import annotations

import json

from pydantic import Field

import db
from business_common import RO, _Base


class FindAgentsIn(_Base):
    department_id: int | None = Field(None, description="Only agents in this department")
    status: str | None = Field(
        None, description="'candidate', 'active', 'suspended' or 'offboarded'"
    )
    kind: str | None = Field(
        None,
        description="'orchestrator', 'subagent' or 'voice' — filters by agent_kind "
                    "(db/072; voice added db/091)",
    )


class AgentProfileIn(_Base):
    agent_member_id: int | None = Field(
        None, description="Defaults to the caller when the caller is itself an agent"
    )


class HrHistoryIn(_Base):
    member_id: int
    include_reviews: bool = Field(True, description="Also include performance reviews")


class AgentRunsIn(_Base):
    agent_member_id: int | None = Field(None, description="Only this agent's runs. Defaults to the caller when the caller is an agent")
    status: str | None = Field(None, description="'running', 'awaiting_approval', 'succeeded', 'failed' or 'cancelled'")
    days: int = Field(7, ge=1, le=365, description="How far back to look")
    parent_run_id: int | None = Field(None, description="Only the runs this run delegated")
    limit: int = Field(25, ge=1, le=100)


class AgentConversationsIn(_Base):
    agent_member_id: int | None = Field(None, description="Only your conversations with this agent")
    include_archived: bool = Field(False, description="Also the ones you archived")
    limit: int = Field(25, ge=1, le=100)


class AgentConversationReadIn(_Base):
    conversation_id: int = Field(..., description="One of YOUR conversations, from agent_conversations")
    limit: int = Field(20, ge=1, le=100, description="The most recent turns, returned oldest first")


class AgentPerformanceIn(_Base):
    agent_member_id: int | None = Field(None, description="One agent. Omit for every agent you may see")
    days: int = Field(30, ge=1, le=365, description="The period: how many days back from now")


class LedgerCallsIn(_Base):
    agent_run_id: int | None = Field(None, description="Only the model calls of this run")
    agent_member_id: int | None = Field(None, description="Only this agent's calls")
    status: str | None = Field(None, description="'ok', 'error', 'timeout', 'rate_limited', 'refused' or 'cancelled'")
    days: int = Field(7, ge=1, le=365)
    limit: int = Field(50, ge=1, le=200)


class PromptForRequestIn(_Base):
    request_id: str = Field(..., description="The request_id from record_history (activity server) or from agent_runs")
    include_payloads: bool = Field(True, description="Include the full context sent and the response received")


def register(mcp, q) -> None:
    """Attach the Agent HR tools; `q(sql, *args)` runs a member-scoped read."""

    # ---- find_agents (H2, H5) ------------------------------------------------
    @mcp.tool(name="find_agents", annotations={"title": "Find agents", **RO})
    async def find_agents(params: FindAgentsIn) -> str:
        """Which agents we employ, what each does, who manages them, their model and monthly
        budget. Each row carries agent_kind ('orchestrator', 'subagent' or 'voice'): an
        orchestrator may hold a roster and delegate, a subagent does the work and never
        re-delegates, a voice agent answers inbound calls and takes no part in delegation
        (db/072, db/091); subagent_count/orchestrator_count give the live roster size from
        whichever side applies, and are zero for a voice agent. Call for "which agents do we
        have", "who manages the support agent", "what is the bookkeeping agent's budget",
        "which agents are orchestrators", "which agents answer the phone".
        Job descriptions and budgets are hidden from a caller who holds no hr grant, is not the
        agent's manager and is not the agent itself — such a caller still sees the row, just
        with those fields blank."""
        where = ["1 = 1"]
        args: list = []
        if params.status:
            args.append(params.status)
            where.append(f"a.status = ${len(args)}")
        else:
            where.append("a.status <> 'offboarded'")
        if params.department_id is not None:
            args.append(params.department_id)
            where.append(
                f"EXISTS (SELECT 1 FROM mcp_department_members dm "
                f"WHERE dm.member_id = a.agent_member_id AND dm.department_id = ${len(args)} "
                f"AND dm.left_at IS NULL)"
            )
        if params.kind in ("orchestrator", "subagent", "voice"):
            args.append(params.kind)
            where.append(f"a.agent_kind = ${len(args)}")
        return await q(
            f"""
            SELECT a.agent_member_id, a.display_name, a.job_title, a.status, a.agent_kind,
                   a.is_office_manager, a.description, a.role_key, a.profile_pic_url,
                   a.manager_member_id, a.manager_name, a.home_location_id, a.model_key, a.harness,
                   a.monthly_budget_amount, a.budget_currency, a.hired_at, a.suspended_at,
                   a.offboarded_at, a.subagent_count, a.orchestrator_count
              FROM mcp_agents a
             WHERE {' AND '.join(where)}
             ORDER BY a.display_name
             LIMIT 200
            """,
            *args,
        )

    # ---- agent_profile (H3, H7, H10) -----------------------------------------
    @mcp.tool(name="agent_profile", annotations={"title": "Agent profile", **RO})
    async def agent_profile(params: AgentProfileIn) -> str:
        """One agent's job description, model, tool grants, schedule and config history — what
        it may do, and what it needs a human for. Each config version's harness_config carries
        its resolved model parameters (temperature, max_tokens, ...); system_prompt_id/version
        name the library prompt it cites, or both are null when its text was written inline for
        this agent alone. An agent calling this with no agent_member_id gets its own profile.
        "roster" lists the live agent_subagents rows this agent sits in either side of
        (db/072): for an orchestrator, the subagents it may delegate to; for a subagent, the
        orchestrator(s) it serves. Call for "what is this agent's job", "what tools does it
        have", "what changed in its last configuration version", "which prompt version is it
        running", "which subagents does this orchestrator manage", "who does this agent report
        to for delegation"."""
        agent_id = params.agent_member_id
        if agent_id is None:
            agent_id = db.request_member_id.get()
        if agent_id is None:
            return '{"error": "agent_member_id is required unless the caller is itself an agent"}'
        agent = await q(
            """
            SELECT a.*, td.email
              FROM mcp_agents a
              LEFT JOIN mcp_team_directory td ON td.member_id = a.agent_member_id
             WHERE a.agent_member_id = $1
            """,
            agent_id,
        )
        versions = await q(
            """
            SELECT v.config_version_id, v.version_no, v.job_description, v.model_id, v.change_note,
                   v.harness_config, v.created_by, v.created_at, v.gating_eval_run_id, v.activated_at,
                   v.activated_by, v.system_prompt_id, v.system_prompt_version,
                   v.system_prompt_key, v.system_prompt_name
              FROM mcp_agent_config_versions v
             WHERE v.agent_member_id = $1
             ORDER BY v.version_no DESC
             LIMIT 20
            """,
            agent_id,
        )
        grants = await q(
            """
            SELECT application_endpoint_id, endpoint_name, endpoint_url, mcp_surface_version,
                   application_id, application_name, application_category,
                   tool_name, constraints, granted_by, created_at
              FROM mcp_agent_tool_grants
             WHERE agent_member_id = $1
             ORDER BY endpoint_name, tool_name
            """,
            agent_id,
        )
        duties = await q(
            """
            SELECT duty_id, name, instructions, schedule_cron, timezone, active, last_run_at, next_run_at
              FROM mcp_agent_duties
             WHERE agent_member_id = $1
             ORDER BY name
            """,
            agent_id,
        )
        # The roster (db/072): an orchestrator's live subagents, or the orchestrators a subagent
        # serves — the same mcp_agent_subagents view, read from whichever side this agent sits on.
        roster = await q(
            """
            SELECT agent_subagent_id, orchestrator_member_id, orchestrator_name,
                   subagent_member_id, subagent_name, subagent_status, subagent_role_key,
                   note, added_by, added_at
              FROM mcp_agent_subagents
             WHERE (orchestrator_member_id = $1 OR subagent_member_id = $1) AND removed_at IS NULL
             ORDER BY added_at
            """,
            agent_id,
        )
        return (
            '{"agent": ' + agent
            + ', "config_versions": ' + versions
            + ', "tool_grants": ' + grants
            + ', "duties": ' + duties
            + ', "roster": ' + roster + '}'
        )

    # ---- hr_history (H12, H13) ------------------------------------------------
    @mcp.tool(name="hr_history", annotations={"title": "HR history", **RO})
    async def hr_history(params: HrHistoryIn) -> str:
        """Hire, suspend, reinstate, offboard and other HR events for a person or an agent —
        the employment record. Call for "when was this agent hired", "who suspended them and
        why", "show the review history"."""
        events = await q(
            """
            SELECT hr_event_id, member_id, display_name, member_kind, event_type,
                   config_version_id, note, actor_member_id, occurred_at
              FROM mcp_hr_events
             WHERE member_id = $1
             ORDER BY occurred_at DESC
             LIMIT 200
            """,
            params.member_id,
        )
        if not params.include_reviews:
            return '{"events": ' + events + '}'
        reviews = await q(
            """
            SELECT review_id, member_id, reviewer_member_id, period_start, period_end,
                   rating, summary, metrics, created_at
              FROM mcp_performance_reviews
             WHERE member_id = $1
             ORDER BY period_end DESC
             LIMIT 50
            """,
            params.member_id,
        )
        return '{"events": ' + events + ', "reviews": ' + reviews + '}'

    # ---- agent_runs (H4, DB7, PL7) --------------------------------------------
    @mcp.tool(name="agent_runs", annotations={"title": "Agent runs", **RO})
    async def agent_runs(params: AgentRunsIn) -> str:
        """What an agent is doing or did: its runs with what each was asked, what it answered,
        its status, trigger and cost. Call for "what is Sasha working on", "what is running right
        now", "what did the agents do today", "which runs are waiting for approval", "what did
        that run delegate". Follow a run's request_id into prompt_for_request for its model calls,
        or into the activity server's record_history for what it changed."""
        runs = await q(
            """
            SELECT agent_run_id, agent_member_id, agent_name, trigger, duty_id, status, harness,
                   sdk_version, request_id, instructions, result, error, parent_run_id,
                   approval_request_id, input_tokens, output_tokens, cost, currency,
                   started_at, finished_at
              FROM mcp_agent_runs
             WHERE ($1::bigint IS NULL OR agent_member_id = $1)
               AND ($2::text IS NULL OR status = $2)
               AND ($3::bigint IS NULL OR parent_run_id = $3)
               AND started_at >= now() - make_interval(days => $4)
             ORDER BY started_at DESC
             LIMIT $5
            """,
            params.agent_member_id, params.status, params.parent_run_id, params.days, params.limit,
        )
        return '{"runs": ' + runs + '}'

    # ---- agent_conversations / agent_conversation_read (agent-chat.md, db/163) --
    @mcp.tool(name="agent_conversations", annotations={"title": "My chats with agents", **RO})
    async def agent_conversations(params: AgentConversationsIn) -> str:
        """The caller's own chat threads with agents (the Chat tab on an agent's page): title, which
        agent, how many turns, when it began. A conversation is private to the person who had it, so
        this never lists anyone else's. Call for "what did I ask Sasha last week", "find my chat about
        the hiring plan". Read one with agent_conversation_read."""
        rows = await q(
            """
            SELECT conversation_id, agent_member_id, agent_name, title, turns, last_run_id, created_at, archived_at
              FROM mcp_agent_conversations
             WHERE ($1::bigint IS NULL OR agent_member_id = $1)
               AND ($2::boolean OR archived_at IS NULL)
             ORDER BY coalesce(last_run_id, 0) DESC, conversation_id DESC
             LIMIT $3
            """,
            params.agent_member_id, params.include_archived, params.limit,
        )
        return '{"conversations": ' + rows + '}'

    @mcp.tool(name="agent_conversation_read", annotations={"title": "Read a chat with an agent", **RO})
    async def agent_conversation_read(params: AgentConversationReadIn) -> str:
        """The turns of one of the caller's own chats with an agent, oldest first: what the person said,
        what the agent answered, each turn's state and cost, and the run behind it (follow run_id into
        prompt_for_request for its model calls). Refuses a conversation that is not the caller's."""
        turns = await q(
            """
            SELECT * FROM (
              SELECT r.agent_run_id AS run_id, r.status, r.chat_utterance AS said, r.result AS reply, r.error,
                     r.approval_request_id, r.cost, r.currency, r.started_at, r.finished_at, r.request_id
                FROM mcp_agent_conversations c
                JOIN mcp_agent_runs r ON r.conversation_id = c.conversation_id
               WHERE c.conversation_id = $1
               ORDER BY r.agent_run_id DESC
               LIMIT $2) t
             ORDER BY run_id
            """,
            params.conversation_id, params.limit,
        )
        return '{"turns": ' + turns + '}'

    # ---- agent_performance (H4, H8, DB7) --------------------------------------
    @mcp.tool(name="agent_performance", annotations={"title": "Agent performance", **RO})
    async def agent_performance(params: AgentPerformanceIn) -> str:
        """How agents perform over a period: runs (succeeded, failed, waiting for approval),
        escalations and what they were about, spend this month
        against budget, the latest eval score, and how many of their actions needed approval.
        Call for "how is Sasha doing", "which agent escalates most", "who is near budget",
        "is any agent failing". Pair with the activity server's activity_summary for action
        counts. Only agents you may see in full (HR, the agent's manager, the agent itself)."""
        agents = await q(
            """
            SELECT a.agent_member_id, a.display_name, a.job_title, a.status, a.agent_kind,
                   a.manager_name, a.model_key, a.budget_currency,
                   -- the budget that is enforced is the ACTIVE VERSION's (the ledger proxy reads
                   -- it there); activating a version does not copy it onto the profile
                   COALESCE((SELECT v.monthly_budget_amount FROM mcp_agent_config_versions v
                              WHERE v.config_version_id = a.current_config_version_id),
                            a.monthly_budget_amount) AS monthly_budget_amount,
                   (SELECT COALESCE(sum(r.cost), 0) FROM mcp_agent_runs r
                     WHERE r.agent_member_id = a.agent_member_id
                       AND r.started_at >= date_trunc('month', now())) AS spend_this_month,
                   (SELECT jsonb_build_object(
                             'total', count(*),
                             'succeeded', count(*) FILTER (WHERE r.status = 'succeeded'),
                             'failed', count(*) FILTER (WHERE r.status = 'failed'),
                             'awaiting_approval', count(*) FILTER (WHERE r.status = 'awaiting_approval'),
                             'cancelled', count(*) FILTER (WHERE r.status = 'cancelled'),
                             'cost', COALESCE(sum(r.cost), 0),
                             'last_started_at', max(r.started_at))
                      FROM mcp_agent_runs r
                     WHERE r.agent_member_id = a.agent_member_id
                       AND r.started_at >= now() - make_interval(days => $2)) AS runs,
                   (SELECT jsonb_build_object(
                             'total', count(*),
                             'open', count(*) FILTER (WHERE x.resolved_at IS NULL),
                             'by_reason', COALESCE((SELECT jsonb_object_agg(reason_kind, n) FROM (
                                 SELECT y.reason_kind, count(*) AS n FROM mcp_agent_escalations y
                                  WHERE y.agent_member_id = a.agent_member_id
                                    AND y.created_at >= now() - make_interval(days => $2)
                                  GROUP BY y.reason_kind) g), '{}'::jsonb))
                      FROM mcp_agent_escalations x
                     WHERE x.agent_member_id = a.agent_member_id
                       AND x.created_at >= now() - make_interval(days => $2)) AS escalations,
                   (SELECT jsonb_build_object(
                             'total', count(*),
                             'pending', count(*) FILTER (WHERE p.status = 'pending'),
                             'approved', count(*) FILTER (WHERE p.status IN ('approved', 'executed', 'execution_failed')),
                             'rejected', count(*) FILTER (WHERE p.status = 'rejected'),
                             'cancelled_or_expired', count(*) FILTER (WHERE p.status IN ('cancelled', 'expired')))
                      FROM mcp_approval_requests p
                     WHERE p.requested_by_member_id = a.agent_member_id
                       AND p.created_at >= now() - make_interval(days => $2)) AS approvals_needed,
                   (SELECT jsonb_build_object('eval_set', e.eval_set_name, 'status', e.status, 'score', e.score,
                             'pass_threshold', e.pass_threshold, 'finished_at', e.finished_at)
                      FROM mcp_eval_runs e
                     WHERE e.agent_member_id = a.agent_member_id AND e.status IN ('passed', 'failed')
                     ORDER BY e.finished_at DESC LIMIT 1) AS latest_eval
              FROM mcp_agents a
             WHERE app_can_see_agent(a.agent_member_id)
               AND ($1::bigint IS NULL OR a.agent_member_id = $1)
             ORDER BY a.display_name
            """,
            params.agent_member_id, params.days,
        )
        recent = await q(
            """
            SELECT escalation_id, agent_member_id, agent_name, reason_kind, summary, resolved_at, created_at
              FROM mcp_agent_escalations
             WHERE ($1::bigint IS NULL OR agent_member_id = $1)
               AND created_at >= now() - make_interval(days => $2)
             ORDER BY created_at DESC
             LIMIT 20
            """,
            params.agent_member_id, params.days,
        )
        return ('{"period_days": ' + str(params.days) + ', "agents": ' + agents
                + ', "recent_escalations": ' + recent + '}')

    # ---- ledger_calls (PL3, PL7) ----------------------------------------------
    @mcp.tool(name="ledger_calls", annotations={"title": "Model calls in the prompt ledger", **RO})
    async def ledger_calls(params: LedgerCallsIn) -> str:
        """Individual model calls from the prompt ledger: failures, timeouts, rate limits and
        budget refusals; every call a run made, with tokens, latency and cost. Call for "why did
        that run fail", "which calls were refused for budget", "how many model calls did this
        duty take". Metadata only — prompt_for_request returns the prompt itself."""
        calls = await q(
            """
            SELECT ledger_id, occurred_at, agent_run_id, agent_member_id, harness, provider,
                   provider_model_id, request_id, status, error_code, error_message,
                   input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                   latency_ms, cost, currency
              FROM mcp_prompt_ledger
             WHERE ($1::bigint IS NULL OR agent_run_id = $1)
               AND ($2::bigint IS NULL OR agent_member_id = $2)
               AND ($3::text IS NULL OR status = $3)
               AND occurred_at >= now() - make_interval(days => $4)
             ORDER BY occurred_at DESC
             LIMIT $5
            """,
            params.agent_run_id, params.agent_member_id, params.status, params.days, params.limit,
        )
        return '{"calls": ' + calls + '}'

    # ---- prompt_for_request (PL2) ---------------------------------------------
    @mcp.tool(name="prompt_for_request", annotations={"title": "The prompt behind an action", **RO})
    async def prompt_for_request(params: PromptForRequestIn) -> str:
        """The full prompt and response behind an action: every model call that shares a
        request_id, in order, with the exact context sent (system prompt, messages, tool
        definitions) and the response. Get the request_id from the activity server's
        record_history, or from agent_runs. An agent sees only its own calls."""
        calls = await q(
            """
            SELECT l.ledger_id, l.occurred_at, l.agent_run_id, l.agent_member_id, l.provider_model_id,
                   l.status, l.input_tokens, l.output_tokens, l.cost, l.latency_ms,
                   CASE WHEN $2 THEN p.context END AS context,
                   CASE WHEN $2 THEN p.response END AS response,
                   p.byte_size, (p.ledger_id IS NULL) AS payload_withheld_or_archived
              FROM mcp_prompt_ledger l
              LEFT JOIN mcp_prompt_payloads p ON p.ledger_id = l.ledger_id
             WHERE l.request_id = $1
             ORDER BY l.occurred_at
             LIMIT 100
            """,
            params.request_id, params.include_payloads,
        )
        return '{"request_id": ' + json.dumps(params.request_id) + ', "calls": ' + calls + '}'
