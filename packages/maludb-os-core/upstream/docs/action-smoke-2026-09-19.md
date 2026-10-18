# Action smoke through the actions MCP — 2026-09-19

The first time any write was exercised end to end here. Run as the owner (member 1) with
`mcp/smoke_actions.py` — the assistant's own door: streamable HTTP to `127.0.0.1:8813`, a
signed action token, one MCP tool per built action. The owner authorised it ("smoke tests can
write to anything"). Everything it made is named **`SMOKE <run>`** and addressed to
`…@example.invalid`; mail went nowhere real. Scenarios: `mcp/smoke/*.json`
(`venv/bin/python smoke_actions.py run smoke/1-crm-sales.json`).

**Coverage: 110 tool calls across 106 of the 163 built actions. 82 succeeded. The 28 that did
not: 12 hit a defect tabled below, 2 are still to be checked (row 7), 8 were knock-ons of an
earlier failure in the same chain (a record that was never made), and 6 were the scenario's own
mistakes or correct refusals (an already-submitted expense, an agent named instead of numbered,
a human raising an agent's escalation).** Not yet
exercised: agent hire / config / runs / roster, bank import / match / reconcile, approvals,
merges, hard deletes of sales documents, quote decline, business settings, member roles.

## What works (the chains that matter)

- **CRM → cash, whole:** company → contact → primary → tag, note, logged call → deal → stage →
  won → quote → line → send → accept → convert → invoice → line → send → reminder → payment →
  unallocate → allocate → credit note → issue → statement.
- **Projects & tasks:** project → member → milestone → tasks → assign → dependency → blocked →
  reschedule → checklist → complete → reopen → deletes → archive.
- **Expenses:** category → expense → approve → paid; reject → delete; recurring create / pause /
  delete; category archive.
- **Books & settings:** GL account, fiscal period close / reopen, journal entry, **post
  documents (3 posted)**, tax rate, catalogue item, pipeline, department + membership, module
  grant / revoke, application register / grant / health / retire, model save, MCP token.
- **Refusals are right:** an empty or ambiguous reference is refused, never guessed; a
  destructive tool without `confirmed` answers `needs_confirmation`; a human cannot raise an
  agent's escalation.

## Defects found — all in the agents' door, all older than the React migration

The React forms post the handlers' real field names, so none of these touches a screen. They
are why an agent or the command bar cannot do these things today.

| # | Defect | Evidence |
| --- | --- | --- |
| 1 | **Ten `*_update` tools cannot succeed.** The manifest says "the record, plus any field of `<x>_create`"; `bin/build_action_registry.php` turned that phrase into an empty parameter, so the tool takes only the record and the save handler refuses the empty form ("A company needs a name"). organization, contact, deal, interaction, quote, invoice, expense, recurring_expense, project, task. **Not a one-line fix:** the handlers demand the whole form, and refilling it from the `mcp_*` views would wipe the columns those views hide (`tax_id`, a deal's probability override) — the bug class already found twice. Needs a rule for partial updates in action mode. | registry params `['organization', None]` |
| 2 | **`profile_update`** — same class: every field optional in the tool, display name + timezone required by the handler. | "A display name and a valid timezone are required." |
| 3 | **A new pipeline can never get its first stage.** `mcp_pipelines` inner-joins pipelines to stages, so a pipeline with none is invisible to the resolver. Needs a migration (LEFT JOIN). | `pipeline_save` ok → `pipeline_stage_save`: "No pipeline matching…" |
| 4 | **Tool parameter ≠ handler field.** `bank_account_save` sends `gl_account`, the handler reads `gl_account_id`; `location_save` sends `parent_location` / `owner`, the handler reads `parent_location_id` / `owner_member_id`, and requires `siting`, which the tool does not have — so no office or desk can be made; `performance_review_create` sends `period`, the handler wants a start and an end; `system_prompt_save` has no parameter for the first version's text, which the handler requires. | each refused with the handler's own validation message |
| 5 | **A create answers a sentence, never the new id**, while most follow-on tools need an id (only 11 record types resolve by name: organization, contact, deal, interaction, member, department, pipeline, stage, project, invoice, ticket). An agent that creates an expense cannot then submit it without a separate records lookup. | every `*_create` result |
| 6 | `accountant_export_create`: `includes` is optional in the tool and required by the handler. | "Pick at least one of invoices, payments or expenses" |
| 7 | To check: `application_access_revoke` (404 with a valid grant id) and `tag_remove` (400) — likely the same parameter-name class as 4; `journal_entry_save` "succeeds" with flat `debit` / `credit` and no account, where the manifest has `lines[]` — what it saved needs looking at. | wave 3 |

## For cut-over

The actions server posts with `HX-Request: true` and reads `X-Action-Status` headers — the
HTML/HTMX mode. **When the HTML branches are deleted it must ask for JSON instead**
(`Accept: application/json`; `json_mode_finish()` already answers every handler). That is a
change to `mcp/actions_server.py`'s `app_post()` and belongs in the flip, before the deletion.

## Static audit (no writes)

176 write handlers outside the unported cert-study modules: **every one a React screen posts to
reports its outcome** (168 directly through `emit_action_status()` / `respond_*`, the approvals
trio through shared helpers). So a React write that succeeds will not show a false "not
converted" error.

## Fixed the same day (the owner: "Fix and cut over") — verified by `mcp/smoke/4-fixes.json` and `5-…`

| # | Fix |
| --- | --- |
| 1 | `bin/build_action_registry.php` expands "any field of x_create" into that action's fields (all optional) and marks the action `partial`; the tool then posts `_partial=1`, and **`app/partial_update.php`** fills whatever was not sent from the record's own row — the BASE TABLE, never a view, and only for a record the caller can see, only under an action token (a browser cannot trigger it). No save handler was edited. Verified: all ten updates succeed and the hidden columns survive (tax id, a 35 % probability override, the address, the relationship type). |
| 2, 4, 6, 7 | The manifest rows now name the fields the handlers read: `gl_account_id`; `parent_location_id` / `owner_member_id` / `siting`; `period_start` / `period_end`; `system_prompt` (the text) and `prompt` (the id); `application` on a revoke; `includes[]` required; `display_name` and `timezone` required on `profile_update`; `tag` is an id. |
| 3 | `db/103`: `mcp_pipelines` is a LEFT JOIN, as its PHP readers always assumed. Name resolution is `DISTINCT`, so a pipeline with six stages is one match, not six. |
| 5 | The actions server reads PHP's JSON answer and returns **`record_id`** (the tail of the `location` PHP already reports) with every create and update. |
| — | The access-grant handler leaked a raw constraint error to the caller on a duplicate; `application_trigger_message()` now passes through only messages our own triggers raise, and words the duplicate. |
| — | **`mcp/actions_server.py` posts in JSON mode** (`Accept: application/json`), no longer as HTMX — the runbook's step 5a, done and smoke-tested before the flip. |
