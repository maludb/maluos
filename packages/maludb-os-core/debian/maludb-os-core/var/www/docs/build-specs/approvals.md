# Build spec: Approvals — the queue, one request, and the policies

2026-09-19 · Module 1 of the stubbed modules (`docs/build-specs/stub-modules-decisions.md`).
The decide-and-execute half is already built (`docs/build-specs/approvals-execution.md`:
`html/approvals/{approve,reject,cancel}.php`, `app/features/approvals/`). This spec adds what is
missing; it changes none of that.

## Screens (manifest, "Approvals")
| Screen | React route | PHP read | Gate |
| --- | --- | --- | --- |
| `approvals` | `/approvals?role=&status=` | `html/approvals/index.php` (exists; the stub fallback goes) | signed in — the rows are the caller's own |
| `approval-view` | `/approvals/{id}` | `html/approvals/view.php` (new) | the request must be visible through `mcp_approval_requests` |
| `approval-policies-settings` | `/settings/approval-policies` | `html/settings/approval-policies/index.php` | insider (the view's gate); buttons only for a super-admin |
| `approval-policy-add` / `-edit` | `/settings/approval-policies/new`, `/{id}/edit` | `…/form.php` | super |

`approval-view` shows the summary, the action, its parameters as a key/value list, the amount,
who asked (and the agent run behind it, linked), the policy that caught it, the approver, the
timeline (asked → decided → executed, or the execution error), and — for whoever may — Approve
(with a note), Reject (a reason is required) and Withdraw. Who may is decided in PHP and sent as
`can`: approve / reject = the approver while pending; cancel = the requester, or the nearest
human manager of a requesting agent, while pending. Approving is never delegable to an agent
(manifest) — the existing handler enforces it.

## Actions
`approval_approve`, `approval_reject`, `approval_cancel` — built. New, all **super**, all
destructive-confirm in the manifest:
| Action | Handler | Notes |
| --- | --- | --- |
| `approval_policy_save` | `html/settings/approval-policies/save.php` | name, category (money_out / deletion / external_send / other), action_pattern (`entity.verb`, `entity.*`, `*.verb`), applies_to (agents / agent / department / everyone) with its agent or department, amount_threshold + currency, approver, expires_after_hours. The table's CHECKs are the validation's source. |
| `approval_policy_set_active` | `…/active.php` | policy, active |
| `approval_policy_delete` | `…/delete.php` | policy. A policy that caught requests keeps them (`policy_id` is nullable on delete) — checked before building. |
Events: `approval_policy.save`, `approval_policy.set_active`, `approval_policy.delete`.

## Read tools (tool surface)
`approval_queue` — built. New in `mcp/business_approvals.py`: `approval_policy`
(`agent_member_id?`, `department_id?`, `action_key?` over `mcp_approval_policies`) and
`approval_history` (`period`, `status?`, `decided_by?`, `category?` over
`mcp_approval_requests`, with decision times).

## Not in this slice
Time-sheet approval (`/time/approvals`) belongs to Time. Content approvals belong to Content.
