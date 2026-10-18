# Kernel spec: K38 — the run facts say who an agent's run acts for

2026-10-10 · built the same day, at the owner's choice ("Build K38 now") during the Data Lake's Phase 1 walk-through
(`/srv/apps/datalake/docs/datalake-design.md` §12, `docs/phase1-consistency.md` ★2).

## Why
An application whose data is bounded by a person's rights (the Data Lake's masks, row filters and grants) must not let an agent answering that
person read more than the person may. The kernel already records who started a run (`agent_runs.requested_by`: the chat endpoint passes the
acting member, a manual run the person who started it, a delegation the orchestrator's requester) but the run-facts answer never said it. Without
it the Data Lake fails closed: an agent in a person's chat turn is refused every confidential or personal dataset (`k38_pending`).

## What
`POST /api/v1/runs/facts.php` (A7 (b)) answers three more keys, additively — an application that does not read them is unaffected:

| Key | Value |
|---|---|
| `requested_by_member_id` | for an agent's run with trigger `chat`, `manual` or `delegation`: `agent_runs.requested_by`; else `null` (a duty, an evaluation, a message, a person's token, a requester equal to the agent itself) |
| `requested_by_kind` | `human` or `agent` (an orchestrating assistant that delegated), else `null` |
| `requested_by_holds` | whether that member is active and holds THIS application (`sso_member_holding()` — the sign-on claims' holding); `false` when null |

The rule is one function, `run_facts_requester(PDO, int $applicationId, int $runId, int $agentMemberId)` in `app/features/applications/sso.php`;
the endpoint calls it for an agent's run token and answers the three nulls for a person's token.

## What an application does with it (the integration plugin's `agents.md`)
Set the requester as the person the run acts for (the Data Lake: `app.on_behalf_of`) and **intersect**: the lower level, both row filters, the
union of masks. A requester who does not hold the application leaves the agent with nothing of the person's (the intersection is empty). The
Data Lake keeps its fail-closed ceiling (`internal_unpersonal`) for a kernel that does not answer these keys.

## Proof
`php bin/test_run_facts_requester.php` — read-only, on the host's own runs: a chat run answers its requester and whether they hold the
application; a run asked of another agent answers nobody; a duty, an evaluation and a message answer nobody; the endpoint carries the three
keys for every caller. 8 checks green (2026-10-10).
