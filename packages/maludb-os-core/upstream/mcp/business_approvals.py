"""Approvals — the read side (docs/build-specs/approvals-execution.md).

Deciding is an ACTION (approval_approve / approval_reject / approval_cancel on the actions server),
never a tool here; this module answers "what is waiting". mcp_approval_requests scopes the rows:
a caller sees what they asked for, what waits on them, what they decided, and — with the approvals
module or as an agent's manager — more. request_body (what the platform replays) is not in the view
and not here: summary, parameters and amount are what a decision is made on.

Registered by records_server.py; the module never opens its own connection.
"""
from __future__ import annotations

from pydantic import Field

from business_common import RO, _Base


class ApprovalQueueIn(_Base):
    role: str = Field("approver", description="'approver' = what is waiting for MY decision; 'requester' = "
                                              "what I (or, for a manager, my agents) asked for; 'all' = everything I may see")
    status: str | None = Field("pending", description="'pending', 'approved', 'rejected', 'expired', 'cancelled', "
                                                      "'executed' or 'execution_failed'; null for every status")
    limit: int = Field(50, ge=1, le=200)


def register(mcp, q, current_member_id) -> None:
    """Attach the approvals tools; `q(sql, *args)` runs a member-scoped read."""

    # ---- approval_queue (AP1, AP5) -------------------------------------------
    @mcp.tool(name="approval_queue", annotations={"title": "Approval queue", **RO})
    async def approval_queue(params: ApprovalQueueIn) -> str:
        """What is waiting for my approval, and the status of requests I made. Call for "what do I
        need to approve", "did my refund request go through", "what are the agents waiting on",
        "why did that approval fail to run". Each request says who asked (a person or an agent),
        the action, a plain summary, the amount if any, the agent run it paused, and — once decided
        — who decided, the note or reason, and whether the action then ran or failed and why.
        To decide one, use the approval_approve or approval_reject ACTION with its
        approval_request_id; rejecting needs a reason."""
        me = current_member_id()
        requests = await q(
            """
            SELECT approval_request_id, status, action_key, summary, parameters, amount, currency,
                   entity_type, entity_id, requested_by_member_id, requested_by_name, requested_by_kind,
                   agent_run_id, approver_member_id, approver_name, decided_by, decided_at,
                   decision_note, created_at, expires_at, executed_at, executed_activity_id, execution_error
              FROM mcp_approval_requests
             WHERE ($1::text IS NULL OR status = $1)
               AND CASE $2 WHEN 'approver'  THEN approver_member_id = $3
                           WHEN 'requester' THEN requested_by_member_id = $3 OR requested_by_kind = 'agent'
                           ELSE true END
             ORDER BY (status = 'pending') DESC, created_at DESC
             LIMIT $4
            """,
            params.status, params.role if params.role in ("approver", "requester") else "all", me, params.limit,
        )
        return '{"role": "' + (params.role if params.role in ("approver", "requester") else "all") + '", "requests": ' + requests + '}'


# ---- approval_policy (AP2, H10) and approval_history (AP3, AP4, AP6, E12) ------------------
# Added with the Approvals screens (docs/build-specs/approvals.md). Registered by
# register_policy_and_history(), which records_server.py calls beside register().
from business_common import _iso_date, _period_bounds  # noqa: E402


class ApprovalPolicyIn(_Base):
    agent_member_id: int | None = Field(None, description="Only policies that would apply to this agent")
    department_id: int | None = Field(None, description="Only policies that would apply to this department")
    action_key: str | None = Field(None, description="An action's event, e.g. 'invoice.send' — returns the policies "
                                                     "whose pattern matches it ('invoice.send', 'invoice.*', '*.send')")
    include_inactive: bool = Field(False, description="Also list policies that are switched off")


class ApprovalHistoryIn(_Base):
    period: str | None = Field("this_month", description="'today', 'this_week', 'last_week', 'this_month', 'last_month', 'this_quarter', 'last_quarter', 'ytd' (this year so far), 'last_12_months' — by when the request was made. Any other "
                                                          "word is read as this_month")
    date_from: str | None = Field(None, description="ISO date; overrides period")
    date_to: str | None = Field(None, description="ISO date; overrides period")
    status: str | None = Field(None, description="'approved', 'rejected', 'expired', 'cancelled', 'executed', "
                                                 "'execution_failed'; null for every decided status")
    decided_by: int | None = Field(None, description="member id of whoever decided")
    category: str | None = Field(None, description="'money_out', 'deletion', 'external_send' or 'other' — the "
                                                   "category of the policy that caught the request")
    requested_by_kind: str | None = Field(None, description="'agent' for what agents asked for, 'human' for people")
    limit: int = Field(100, ge=1, le=200)


def register_policy_and_history(mcp, q) -> None:
    @mcp.tool(name="approval_policy", annotations={"title": "Approval policies", **RO})
    async def approval_policy(params: ApprovalPolicyIn) -> str:
        """Which actions need a person's approval, for whom, above what amount, and who approves.
        Call for "does sending an invoice need approval", "what can this agent not do on its
        own", "what needs approval in Accounting". A policy with no approver goes to the
        requester's nearest human manager. Pass action_key to ask about one action."""
        where = ["1 = 1"]
        args: list = []
        if not params.include_inactive:
            where.append("p.active")
        if params.agent_member_id is not None:
            args.append(params.agent_member_id)
            where.append(f"(p.applies_to IN ('agents', 'everyone') OR p.agent_member_id = ${len(args)})")
        if params.department_id is not None:
            args.append(params.department_id)
            where.append(f"(p.applies_to IN ('agents', 'everyone') OR p.department_id = ${len(args)})")
        if params.action_key:
            args.append(params.action_key)
            n = len(args)
            where.append(f"(p.action_pattern = ${n} OR p.action_pattern = split_part(${n}, '.', 1) || '.*' "
                         f"OR p.action_pattern = '*.' || split_part(${n}, '.', 2))")
        return await q(
            f"""
            SELECT p.policy_id, p.name, p.category, p.action_pattern, p.applies_to, p.agent_member_id,
                   p.department_id, p.amount_threshold, p.currency, p.approver_member_id,
                   ap.display_name AS approver_name, p.expires_after_hours, p.active
              FROM mcp_approval_policies p
              LEFT JOIN mcp_team_directory ap ON ap.member_id = p.approver_member_id
             WHERE {' AND '.join(where)}
             ORDER BY p.category, p.name
            """,
            *args,
        )

    @mcp.tool(name="approval_history", annotations={"title": "Approval history", **RO})
    async def approval_history(params: ApprovalHistoryIn) -> str:
        """What was approved, rejected, withdrawn or left to expire, by whom and how long each
        decision took (decision_minutes). Call for "what did I approve last month", "which
        requests expired", "money-out requests by agents this quarter", "how quickly does Dana
        decide". Only requests the asker may see are returned. Pending requests are
        approval_queue's."""
        where = ["r.status <> 'pending'"]
        args: list = []
        bounds = _period_bounds(params.period, _iso_date(params.date_from), _iso_date(params.date_to))
        if bounds:
            where.append(f"r.created_at >= {bounds[0]} AND r.created_at < {bounds[1]}")
        if params.status:
            args.append(params.status)
            where.append(f"r.status = ${len(args)}")
        if params.decided_by is not None:
            args.append(params.decided_by)
            where.append(f"r.decided_by = ${len(args)}")
        if params.category:
            args.append(params.category)
            where.append(f"p.category = ${len(args)}")
        if params.requested_by_kind:
            args.append(params.requested_by_kind)
            where.append(f"r.requested_by_kind = ${len(args)}")
        args.append(params.limit)
        return await q(
            f"""
            SELECT r.approval_request_id, r.status, r.action_key, r.summary, r.amount, r.currency,
                   r.requested_by_name, r.requested_by_kind, r.approver_name, p.name AS policy, p.category,
                   r.created_at, r.decided_at, r.decision_note, r.executed_at, r.execution_error,
                   round(extract(epoch FROM (r.decided_at - r.created_at)) / 60) AS decision_minutes
              FROM mcp_approval_requests r
              LEFT JOIN mcp_approval_policies p ON p.policy_id = r.policy_id
             WHERE {' AND '.join(where)}
             ORDER BY r.created_at DESC
             LIMIT ${len(args)}
            """,
            *args,
        )
