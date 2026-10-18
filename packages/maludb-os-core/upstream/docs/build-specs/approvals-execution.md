# Build spec: Approvals — decide and execute (stage H3)

> Plan: `docs/hermes-integration-plan.md` (H3). Schema, manifest rows and the tool below were all
> approved already: `approval_requests` (db/044), its replay columns (db/097, H1 checkpoint), the
> actions `approval_approve` / `approval_reject` / `approval_cancel` (manifest, "Approvals") and the
> tool `approval_queue` (tool surface). **This slice adds no schema, no manifest row and no tool
> that was not already approved.**

## Why now

`check_approval()` has paused actions since phase 1: it writes an `approval_requests` row, answers
`pending_approval` and changes nothing. Nothing has ever been able to *answer* one —
`html/approvals/index.php` is a module stub. With agents running (H2) that gap is live: an agent's
run ends `awaiting_approval` and stays there. The manifest already says what must happen: *"On
approval, the app replays the stored parameters through the same endpoint and records
`executed_activity_id`."* H3 builds exactly that.

## Is / is not

**Is:** three write handlers, the replay mechanism, the queue as a JSON read and as an MCP tool,
and an optional follow-up run for an agent requester.
**Is not:** a screen. `app/views/` is frozen and the React approvals screen is stage H7; until then
the queue is reached through the command bar and AI tools (`approval_queue`, then
`approval_approve`), which is how an approver works by voice anyway. Approval-policy settings
(`approval_policy_save`) stay unbuilt.

## The replay — how an approved action runs

The paused request is stored whole (H2): `handler_path` + `request_body` (the POST minus the CSRF
token). On approval PHP **POSTs it again to the same handler on localhost, as the requester**, so
every gate, validation and `log_activity()` line in that handler runs exactly as it would have.
Nothing is executed from `parameters`, which is a human summary.

| Header on the replay | Meaning |
|---|---|
| `X-Action-Token` | `mint_action_token(requester, 120)` — the handler authorises the *requester*, not the approver. |
| `X-Approval-Replay` | `{id}.{hmac}` over `replay:{id}.{handler_path}.{sha256(body)}` keyed on `ACTION_TOKEN_KEY`. |

`check_approval()` lets a request through **only if all of these hold**: the signature verifies;
the row is `approved`; its `action_key`, `handler_path` and body hash match this request; the
caller is the row's requester; and an atomic claim succeeds —
`UPDATE … SET executed_at = now() WHERE id = :id AND status = 'approved' AND executed_at IS NULL`.
The claim makes the bypass **one-use**: a second replay, or a race between two approvers' clicks,
finds `executed_at` set and is paused like any other request. A different action, body or member
with a copied header gets nothing.

Attribution: the replayed action is the requester's. For an agent requester `check_approval()`
restores the run (`agent_run_id` from the row), so the handler's own log line carries
`source='agent'`, the run's `request_id` and `agent_run_id` — one unbroken trail from the prompt
that asked to the change that happened. `log_activity()` records the first activity row written
during a replay as `approval_requests.executed_activity_id`.

Outcome: handler answers `X-Action-Status: ok` → `executed`; anything else → `execution_failed`
with `execution_error`. An approval is never silently "done": the approver sees which.
An action whose input was an uploaded file cannot be replayed (`$_FILES` is not in the body); it
fails as `execution_failed` with that reason. No such action has a policy today.

## Handlers (base `/approvals/`)

All three: `require_post()` + `verify_csrf()` + gate + `log_activity()`, dual-mode through
`emit_action_status()`. **An agent may never decide**: agent callers are refused on all three
("never delegable to agents" in the manifest — and the open question of an orchestrator answering
approvals stays closed until the owner opens it).

| Action | File | Gate | Does |
|---|---|---|---|
| `approval_approve` | `approve.php` — **approval_request**, note, follow_up | the row's `approver_member_id` | `pending` → `approved` (decided_by/at, note) → replay → `executed` \| `execution_failed`. Logs `approval_request.approve`, then `approval_request.execute` with the outcome. |
| `approval_reject` | `reject.php` — **approval_request**, **reason**, follow_up | the approver | `pending` → `rejected`. Logs `approval_request.reject`. |
| `approval_cancel` | `cancel.php` — **approval_request** | the requester; for an agent requester, the agent's manager (the agent's run is over and cannot cancel for itself) | `pending` → `cancelled`. Logs `approval_request.cancel`. |

A request past `expires_at` is marked `expired` when anyone touches it and cannot be decided.

**Follow-up run** (`follow_up=1`, agent requesters only): after the decision the platform starts a
run for the agent — `parent_run_id` = the paused run — telling it what was decided, by whom, the
reason if rejected, the outcome if executed, and its original instructions. Off by default: every
follow-up is model spend, and the approver decides whether the agent has more to do.

## Reads

- `html/approvals/index.php` gains the one JSON branch (`wants_json()` → `respond_screen()`), from
  `app/features/approvals/present.php` — a whitelist presenter. The HTML path stays the module stub.
- MCP tool `approval_queue` (records server, `mcp/business_approvals.py`) over `mcp_approval_requests`:
  `role` (approver / requester), `status?`. Gate: insider (the view scopes the rows).
  `request_body` is **not** in the presenter or the tool: `summary`, `parameters`, amount, requester,
  agent run and age are what an approver decides on.

## Files (exactly these)

```
app/features/approvals/queries.php   find_approval_request, approvals_for_member, decide/claim/finish functions
app/features/approvals/replay.php    approval_replay_signature, approval_replay_verify, replay_approved_request
app/features/approvals/present.php   present_approval_request
app/features/approvals/decide.php    the three decision handlers' shared opening, answers and the follow-up run
html/approvals/approve.php  reject.php  cancel.php  index.php (JSON branch only)
app/business.php                      check_approval(): the replay pass-through
app/activity.php                      executed_activity_id capture; INSERT … RETURNING id
app/features/agents/runs.php          start_agent_run(…, ?int $parentRunId)
mcp/agent_runner/service.py           accepts parent_run_id (already does) — no change expected
mcp/business_approvals.py  mcp/records_server.py (register)
```

## Acceptance

1. An agent run calls a granted action that a policy pauses (`interaction_delete`, policy "Agents:
   any deletion"); the run ends `awaiting_approval`; the record is untouched.
2. `approval_queue` shows it to the approver; an agent caller is refused by `approve.php`; someone
   who is not the approver is refused.
3. The approver approves: the record is deleted **by the handler**, logged with `source='agent'`,
   the run's `request_id` and `agent_run_id`; the request is `executed` with `executed_activity_id`.
4. Replaying the same signed request again is paused, not executed. A tampered body is paused.
5. A rejected request changes nothing and records the reason; a cancelled one likewise.
6. `follow_up=1` starts a child run (`parent_run_id` set).

## Built *(2026-09-19)* — acceptance as run on this server

| # | Result |
|---|---|
| 1 | Run 8 (Sasha, scripted no-cost model) called `interaction_delete`; PHP answered `pending_approval`; the run ended `awaiting_approval` on request 4 with `agent_run_id`, `handler_path` and `request_body` stored; interaction 6 untouched. |
| 2 | `approval_queue` lists it for the approver. An agent caller: 403 *"An agent may ask for approval, never give, refuse or withdraw one."* Another person: 403 *"Only Edward Honour can decide this request."* An ungranted agent cannot even call the tool. |
| 3 | Approved → the delete handler ran → request `executed`, `executed_activity_id` → an `interaction.delete` row with `source='agent'`, actor 44, `agent_run_id` 8 and the run's `request_id`. A second approve: 409. |
| 4 | A **valid** replay signature for a request that was still `pending` → paused, nothing deleted. The same signature on a different body → paused, nothing deleted. A signature is necessary, never sufficient. |
| 5 | Reject without a reason: 422. Rejected and withdrawn requests changed nothing and kept their reason. |
| 6 | Reject with `follow_up=1` started run 10 with `parent_run_id` 9 and the decision, the reason and the original instructions as its brief. |

Three things the spec did not foresee, all fixed in the slice:
- **The approver was an agent.** The default approver is the requester's manager, and Sasha's
  manager is Johnathan, an orchestrator — who may never decide. The request would have waited on
  someone forbidden to answer. `create_approval_request()` now walks the management chain to the
  nearest active **human**; `approval_cancel` uses the same walk (`nearest_human_manager()`).
  Whether an orchestrator may answer approvals stays an open question in the requirements.
- **A decided request left its run `awaiting_approval` forever.** `settle_paused_run()` closes the
  run that is paused on that request (approve, reject, cancel, expire); `db/102` settled the two
  test runs decided before it existed. **Revised 2026-09-27** after Sasha sat "paused for an
  approval" on the dashboard for a week: a run that asked twice was released only when the ONE
  request it was recorded as paused on was decided, and a request nobody opened never expired at
  all (expiry ran only inside the handlers that open a request). Now a run is waiting while ANY of
  its requests is pending and is released when none is (`settle_paused_runs()`);
  `sweep_due_approvals()` expires every overdue request and releases the runs — run by the home
  page, the agent's page and the queue when opened, and by `bin/cron/approvals_expire.php` every
  ten minutes (`docs/deploy/crontab.example`; the owner installs it). And the agent's own page
  carries a **Paused for an approval** card above its tabs: each paused run with its pending
  requests, and the approver decides right there (approve — with "then let the agent carry on",
  the follow-up run, on by default — or reject with a reason), the nearest human manager may
  withdraw; the dashboard card says how many requests wait for the viewer. Sasha's runs 57, 62,
  77 and 92 were released by the first sweep (their requests 15–18, 21, 22 expired, all overdue).
- The shared opening of the three handlers lives in `app/features/approvals/decide.php`, not in the
  web root.

Known and left: requests 2 and 3 (Ledger Bot, from before H2) have no `handler_path`; approving one
answers *"recorded before approvals could replay an action; ask for it again"* — by design. A
follow-up agent can ask for the same thing again; each ask still needs a person, so the cost is
noise, not harm (the scripted model did exactly that, because it re-reads directives in the quoted
instructions — a real model is told not to repeat the request).

## Open Questions

*(none)*
