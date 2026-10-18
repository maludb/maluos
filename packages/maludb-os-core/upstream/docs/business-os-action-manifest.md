# Business OS Action Manifest

2026-09-17 · Edward Honour · **Draft for M1 review (build plan 1.6)**

> The registry the command bar, the actions MCP server and AI agents resolve against. A screen or action missing here can't be reached by voice or by an agent: unfinished design, like a question with no tool.
> Pairs with: `docs/business-os-schema.md` (tables), `docs/business-os-mcp-tool-surface.md` (read tools). Approval defaults: `db/053_seed_approval_policies.sql`.
> The cert-study manifest (`docs/action-manifest.md`) is history: those tables went with the kernel cut, 2026-09-22.

## Summary

- **The kernel's screens and actions** (2026-09-22: the business modules' sections — CRM, sales, expenses, projects, scheduling, tickets, documents, time, content, assets, books, inbox, people, inventory, e-signature, portal, reports, company profile — and the command bar's own tools left this manifest with the kernel cut, db/133; each returns as an application's own manifest). Every table a person or agent changes has its create, update and lifecycle actions, and every list, detail and form page has a screen id.
- **The same endpoints serve three callers:** a person clicking, the command bar acting for a person, and an AI agent acting under its own staff identity. Validation, authorization, activity logging and approval checks run once, in PHP.
- **Agent approvals are designed in.** 18 proposed default policies cover money out, deletions and external sends. A matching action by an agent returns `pending_approval` instead of executing.

## Conventions

### Screens

- **Ids** are kebab-case `{entity}-list`, `{entity}-add`, `{entity}-view`, `{entity}-edit`, plus named screens (`receivables`, `content-calendar`).
- **Canonical URLs:** `/{module}/`, `/{module}/new`, `/{module}/{id}`, `/{module}/{id}/edit`. Needs mod_rewrite (decision 2).
- **Prefill params** in the registry become query-string values the GET controller reads, as in the fork. `{id}` params accept the record id; `navigate` resolves names to ids with the read tools first.
- **Every screen partial stamps** `data-screen`, `data-entity` and `data-record-id` on `#page-content`, so "that", "this invoice" and "add a task here" resolve against the page the user is on.

### Actions

- **Name** `{entity}_{verb}`, snake_case. The **log event** is `{entity}.{verb}`, written by the endpoint with `log_activity()`. Approval policies match these log events.
    - `.delete` means a record is destroyed; `.remove` means something is detached (a line, a member, a dependency). Only `.delete` falls under the "any deletion" policy.
    - Money actions write `amount` and `currency` into the log row's `after`, so thresholds and the audit views work.
- **Endpoints** are POST to `/{module}/{file}.php` with `require_post()`, `verify_csrf()` (or the signed action token), authorization and `log_activity()`. Each section below gives its base path; the table shows the file.
- **Params:** **bold** means required. **A param's name is the field the endpoint reads**, so the actions server can be generated from this table without a translation layer; a `[]` suffix marks a repeated field. A param named for a record (`organization_id`, `member`, `deal`) accepts an id *or* a name and is resolved server-side. A record param takes a name, number or id ("the Acme invoice", "INV-00042", `42`). An ambiguous match fails with the candidates, so the assistant asks one short question.
- **Who** is enforced in the endpoint, with the same gates as the tool surface: `mod:x` means a super-admin, a dept-admin acting inside a department they administer, or a holder of module grant x; `admin` means a super-admin or a dept-admin within their departments; `super` means super-admin only; `all` means any signed-in member; `own` means the record's owner, assignee or requester.
- **Undo** is the inverse applied by `undo_last`. An em dash (—) means it can't be undone (an email went out); the reply says so instead of offering Undo.
- **Confirm (✔)** means the command bar asks before executing: destructive actions, and external sends (decision 4). Everything else executes immediately with an Undo.
- **Agent approval** names the category of the default policy that pauses the action when an agent performs it: `money`, `delete` or `send`. Humans are never paused by the defaults.
- **Refresh:** a data action returns `HX-Trigger: {entity}Changed` (camelCase entity), so listening screen regions reload themselves.
- **The per-department admin flag is set by `department_add_member`** (param `is_admin`), on the way in and afterwards: it is what makes a dept-admin an administrator of *that* department and an ordinary user everywhere else, so it belongs to the membership, not to the member.

### Result contract (actions server)

```json
{"status": "success", "did": "Logged 45 min on Acme website redesign", "undo_id": "act_8231", "refresh": "timeEntryChanged"}
{"status": "pending_approval", "did": "Refund of $250.00 to Acme waits for Edward's approval", "approval_request_id": 17}
{"status": "error", "message": "Found 2 invoices for Acme: INV-00041 ($1,200), INV-00042 ($500). Which one?"}
```

For `pending_approval`, the endpoint writes an `approval_requests` row with the action key, parameters and amount, notifies the approver, and executes nothing. On approval, the app replays the stored parameters through the same endpoint and records `executed_activity_id`. Undo of a pending action cancels the request.

> **Generated, not transcribed.** `bin/build_action_registry.php` parses this file into `mcp/action_registry.json`, and the actions server builds `find_screen`, `navigate` and one tool per action from it at startup. A slice's rows are finalised to the endpoint's real field names when the slice is built; until then an action is registered (and findable) but not exposed as a tool, because a tool that would 404 is worse than no tool.

## Home

Screens:

| Screen id | URL | When the user wants… |
| --- | --- | --- |
| `dashboard` | `/` | the business overview: the counts, then the agent workforce — picture, name, department, model and what each is doing right now |
| `launch` | `/launch/{application}` | to open an application signed in through the platform (A3): the hand-off token is minted and the browser sent to the application's sign-on path |
| `launcher` | `/launcher` | the person face's home (app.<domain>, A2 2026-09-22): the applications they may open, one card each, and the operating system for a super-admin |
| `search` | `/search` | to search across all records (params: `q`, `type`) |
| `notifications` | `/notifications` | to read their notifications (params: `unread`) |
| `activity` | `/activity` | to see recent activity, or one record's history (params: `entity_type`, `entity_id`, `member`, `source`, `period`) |

Actions (base `/notifications/`):

| Action | File | Params | Undo | Confirm | Agent approval | Log | Who |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `notification_mark_read` | `read.php` | **notification** | mark unread | | | `notification.mark_read` | own |
| `notification_mark_all_read` | `read-all.php` | kind | mark those unread | | | `notification.mark_all_read` | all |
| `notification_preference_set` | `preference.php` | **kind**, **channel** (in_app/email/digest/off) | restore prior | | | `notification_preference.set` | all |

## Team, access & settings

Screens:

| Screen id | URL | When the user wants… |
| --- | --- | --- |
| `team-list` | `/team/` | who works here, human and AI (params: `department`, `kind`, `role`) |
| `member-view` | `/team/{id}` | one person's role, departments, access, reviews |
| `member-edit` | `/team/{id}/edit` | to change someone's role, departments or module access |
| `invitations` | `/team/invitations` | to invite people and manage pending invites |
| `departments-list` | `/team/departments` | the departments, including the four standing ones (Front Office, HR, Accounting, Audit) and who reports to whom |
| `department-add` | `/team/departments/new` | to create a department |
| `department-view` | `/team/departments/{id}` | one department: manager, members, handbook |
| `department-edit` | `/team/departments/{id}/edit` | to edit a department |
| `external-access` | `/team/external` | who outside the business can see what |
| `settings` | `/settings` | their own profile, notifications, security, tokens (params: `section`) |
| `settings-2fa` | `/settings/2fa` | to set up authenticator 2FA |
| `business-settings` | `/settings/business` | business name, currency, timezone, fiscal year, defaults |
| `email-settings` | `/settings/email` | bounced and suppressed email addresses |
| `backups-settings` | `/settings/backups` | backups and restore rehearsals |
| `exports-settings` | `/settings/exports` | to export all the business's data |

Actions (base `/team/`, settings under `/settings/`):

| Action | File | Params | Undo | Confirm | Agent approval | Log | Who |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `invitation_send` | `invitations/save.php` | **email**, **business_role**, department, message | revoke invite | | send | `invitation.send` | admin (super for the super-admin role) |
| `invitation_resend` | `invitations/resend.php` | **invitation** | — | | send | `invitation.send` | admin |
| `invitation_revoke` | `invitations/revoke.php` | **invitation** | — | ✔ | | `invitation.revoke` | admin |
| `member_set_role` | `/team/role.php` | **member**, **business_role** | restore prior | ✔ | | `member.set_role` | super |
| `member_update` | `/team/update.php` | **member** (a person — agents are maintained in Agent HR), display_name, job_title, phone, timezone (an IANA name) | restore prior | | | `member.update` | admin |
| `member_suspend` | `suspend.php` | **member**, reason | reinstate | ✔ | | `member.suspend` | super |
| `member_reinstate` | `reinstate.php` | **member** | suspend again | | | `member.reinstate` | super |
| `module_grant_set` | `/team/grant.php` | **member**, **module**, **access** (read/write) | restore prior | | | `module_grant.set` | admin |
| `module_grant_revoke` | `/team/grant-revoke.php` | **member**, **module** | grant again | | | `module_grant.revoke` | admin |
| `department_save` | `/team/departments/save.php` | **name**, department, description, handbook_markdown, parent_id, manager_member_id, home_location_id, monthly_budget_amount, budget_currency | restore prior / delete new | | | `department.save` | admin |
| `department_add_member` | `/team/departments/member-add.php` | **department**, **member**, is_admin, is_primary | remove | | | `department_member.create` | admin |
| `department_remove_member` | `/team/departments/member-remove.php` | **department**, **member** | add back | | | `department_member.remove` | admin |
| `department_archive` | `departments/archive.php` | **department**, archived (refused for any standing department) | toggle back | ✔ | | `department.archive` | super |
| `department_delete` | `/team/departments/delete.php` | **department** (only one nothing works in - never a standing department) | — | ✔ | | `department.delete` | super |
| `record_share_create` | `/shares/save.php` | **entity_type**, **entity**, **member**, access, expires_at | revoke | | send | `record_share.create` | admin |
| `record_share_revoke` | `/shares/revoke.php` | **share** | share again | | | `record_share.revoke` | admin |
| `profile_update` | `/settings/profile.php` | **display_name**, **timezone**, job_title, phone | restore prior | | | `member.update` | all (own) |
| `member_default_application_set` | `/settings/default-application.php` | member (omit for yourself), application (one the member holds — omit to clear), scope (a site or department they hold in it) | set the prior one | | | `member.default_application_set` | all (own), admin |
| `channel_identity_link` | `/settings/channels/link.php` | **channel** (telegram or sms or email), address (a phone number with its country code for sms - an email address for email) | remove it | | never delegable to agents | `channel_identity.link` | all (own) |
| `channel_identity_verify` | `/settings/channels/verify.php` | **code** (the six digits texted or mailed to you), channel (sms or email - sms when left out) | remove it | | never delegable to agents | `channel_identity.verify` | all (own) |
| `channel_identity_remove` | `/settings/channels/remove.php` | **identity** | link it again | ✔ | never delegable to agents | `channel_identity.remove` | all (own) |
| `channel_identity_prefer` | `/settings/channels/prefer.php` | **identity** | prefer the prior one | | never delegable to agents | `channel_identity.prefer` | all (own) |
| `business_settings_update` | `/settings/business/save.php` | business_name, legal_name, base_currency, timezone, fiscal_year_start_month, default_payment_terms_days, deal_quiet_days, prompt_payload_retention_days | restore prior | ✔ | | `business_settings.update` | super |
| `business_logo_update` | `/settings/business/logo-save.php` | logo (an uploaded image — JPEG/PNG/GIF/WebP up to 2 MB; browser only), remove_logo (back to the standard logo) | upload the prior file | | | `business_logo.update` / `business_logo.remove` | super |
| `mcp_token_create` | `/settings/tokens/create.php` | **label** (token shown once, on screen only) | revoke | | | `token.create` | all (own) |
| `mcp_token_revoke` | `/settings/tokens/revoke.php` | **token** | — | ✔ | | `token.revoke` | own, super |
| `email_suppression_lift` | `/settings/email/lift.php` | **email** | suppress again | ✔ | | `email_suppression.lift` | admin |
| `backup_run_now` | `/settings/backups/run.php` | — | — | | | `backup_run.start` | super |
| `restore_rehearsal_record` | `/settings/backups/rehearsal-save.php` | **backup**, **status**, notes | delete it | | | `restore_rehearsal.create` | super |
| `data_export_request` | `/settings/exports/request.php` | includes | cancel if still queued | ✔ | | `data_export.create` | super |

**Deleting a department** (2026-09-23) is the super-admin's remedy for one nothing works in. It is refused, by name, while anything is still attached — people or agents who are live members, a named manager, departments that report to it, applications it owns, open invitations into it — or while history names it: a ledger statement line or an eval set (both foreign keys are `ON DELETE SET NULL`, and a closed statement never changes). The four standing departments are never deleted. What goes with the row is the department's own configuration and its dated past — past memberships, approval policies, skill assignments, application access grants — and `department.delete` counts them into the log with what the department was, since `activity_log` holds no foreign key to `departments`. The directory's change feed reports the deletion from that log entry (`deleted_departments`), so an application's mirror drops its row. On `department-view` and `department-edit` the button is disabled with the blockers in its title until the department is empty.

2FA enrollment and disabling stay as in the fork (`totp_enable`, `totp_disable`) and remain screen-first.

## Agents (HR)

Screens:

| Screen id | URL | When the user wants… |
| --- | --- | --- |
| `agents-list` | `/agents/` | the AI agents we employ (params: `department`, `status`) |
| `agent-hire` | `/agents/new` | to hire an agent (params: `department`, `job_title`) |
| `agent-view` | `/agents/{id}` | one agent: job, tools, duties, roster, performance, spend, evals (params: `tab` — job/tools/duties/roster/performance/trail; `roster` only for an orchestrator) |
| `agent-edit` | `/agents/{id}/edit` | to change an agent's job description, model, tools, duties or budget (creates a new version) |
| `agent-versions` | `/agents/versions?agent={id}` | an agent's configuration history and eval gates |
| `escalations` | `/agents/escalations` | escalations raised by agents (params: `agent`, `open`) |
| `review-add` | `/team/reviews/new?member={id}` | to write a performance review for a person or agent |
| `system-prompts` | `/settings/prompts` | the prompt library: reusable system prompts and their versions (params: `role`) |
| `system-prompt-add` | `/settings/prompts/new` | to write a new prompt |
| `system-prompt-view` | `/settings/prompts/{id}` | one prompt: its versions, who uses it, and the text of each |

Actions (base `/agents/`):

| Action | File | Params | Undo | Confirm | Agent approval | Log | Who |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `agent_hire` | `hire.php` | **name**, **job_title**, **department**, **manager**, **model**, **job_description**, **agent_kind** (orchestrator/subagent/voice), monthly_budget, tools[], duties[], home_location, subagents[] (orchestrators only), description, role_key, phone_number (voice agents only, E.164), profile_photo (an uploaded image — JPEG/PNG/GIF/WebP, up to 2 MB) | offboard the candidate | ✔ | | `agent.hire` | mod:hr |
| `agent_update_config` | `config-save.php` | **agent**, job_description, model, tools[], duties[] (name, instructions, schedule), monthly_budget, max_turns, run_timeout_seconds, change_note, description, role_key, phone_number (voice agents only), profile_photo (upload), remove_photo | discard the draft version | | | `agent_config_version.create` | mod:hr, agent's manager |
| `agent_activate_version` | `config-activate.php` | **agent**, **version** (refused without a passing gating eval run) | activate the prior version | ✔ | | `agent_config_version.activate` | mod:hr, agent's manager |
| `agent_set_manager` | `manager.php` | **agent**, **manager** (a human) | restore prior | | | `agent.set_manager` | mod:hr |
| `agent_set_kind` | `/agents/kind.php` | **agent**, **agent_kind** (orchestrator or subagent or voice - refused while a live roster depends on it and an office manager must stay an orchestrator) | restore prior | | | `agent.set_kind` | mod:hr |
| `agent_add_subagent` | `/agents/subagent-add.php` | **agent** (an orchestrator), **subagent**, note (refused if either end is the wrong kind — delegation is one level deep) | remove it | | | `agent_subagent.create` | mod:hr, agent's manager |
| `agent_remove_subagent` | `/agents/subagent-remove.php` | **agent**, **subagent** | add it back | | | `agent_subagent.remove` | mod:hr, agent's manager |
| `agent_run_duty_now` | `run-duty.php` | **agent**, **duty** | — | | | `agent_run.start` | agent's manager, mod:hr |
| `agent_run_start` | `run.php` | **agent**, **instructions** | cancel while running | | never delegable to agents | `agent_run.start` | agent's manager, mod:hr |
| `agent_run_cancel` | `run-cancel.php` | **agent_run** | — | ✔ | | `agent_run.cancel` | agent's manager, mod:hr |
| `agent_chat_send` | `chat-send.php` | **agent**, **message**, conversation (one of yours with this agent - omit to start a new one) | cancel the run while it works | | never delegable to agents; refused while the agent is busy | `agent_chat.send` | agent's manager, mod:hr |
| `agent_chat_rename` | `chat-rename.php` | **conversation**, **title** | rename it again | | never delegable to agents | `agent_chat.rename` | the person the conversation belongs to |
| `agent_chat_archive` | `chat-archive.php` | **conversation**, archive (1 or 0 - default 1) | restore it | | never delegable to agents | `agent_chat.archive` | the person the conversation belongs to |
| `agent_delegate` | `delegate.php` | **subagent**, **instructions**, reason (why this agent - required of a personal assistant), department (which of its departments - default its primary) | cancel the run | | | `agent_run.delegate` | an orchestrator agent, for an agent on its roster (a tree since db/154: an orchestrator may be below it); an assistant only within its person's departments |
| `agent_principal_set` | `principal.php` | **agent**, person (the person it serves - omit to end it) | set the prior person | | never delegable to agents | `agent.principal_set` | super |
| `agent_lead_propose` | `leads/propose.php` | — | decline them | | never delegable to agents | `agent_lead.propose` | super |
| `agent_lead_confirm` | `leads/confirm.php` | **proposal** | offboard the lead | ✔ | never delegable to agents | `agent_lead.confirm` | super |
| `agent_lead_decline` | `leads/decline.php` | **proposal**, note | propose again | | never delegable to agents | `agent_lead.decline` | super |
| `message_send` | `messages/send.php` | **to** (a member - id or name), **body**, subject (a new thread needs one), kind (request or result or question or decision_needed or fyi or reply - default fyi), thread (the thread to answer on), priority (normal or urgent) | — | | | `agent_message.send` | an agent in a run - to its orchestrator or its roster or a lead beside it; a person - to their own assistant |
| `message_done` | `messages/done.php` | **message**, note | — | | | `agent_message.done` | the message's recipient |
| `agent_suspend` | `suspend.php` | **agent**, reason | reinstate | ✔ | | `agent.suspend` | mod:hr, agent's manager |
| `agent_reinstate` | `reinstate.php` | **agent** | suspend again | | | `agent.reinstate` | mod:hr |
| `agent_offboard` | `offboard.php` | **agent**, reason (revokes tokens and grants; trail kept) | — | ✔ | | `agent.offboard` | super |
| `escalation_raise` | `escalation-save.php` | **reason_kind**, **summary**, entity_type, entity, to_member (default: the agent's manager), open_ticket | — | | | `agent_escalation.create` | agents only |
| `escalation_resolve` | `escalation-resolve.php` | **escalation**, note | reopen | | | `agent_escalation.resolve` | escalation recipient, agent's manager |
| `performance_review_create` | `/team/reviews/save.php` | **member**, **period_start**, **period_end**, rating, summary (metrics filled from records and activity) | delete it | | | `performance_review.create` | mod:hr, manager |
| `system_prompt_save` | `/settings/prompts/save.php` | **prompt_key**, **name**, system_prompt (the first version's text — required for a new prompt), description, role_key, prompt (the record's id when editing) | restore prior / delete new | | | `system_prompt.save` | mod:hr |
| `system_prompt_version_create` | `/settings/prompts/version-save.php` | **system_prompt**, **body**, change_note (a new version; existing versions are immutable) | — | | | `system_prompt_version.create` | mod:hr |
| `system_prompt_archive` | `/settings/prompts/archive.php` | **system_prompt**, archived (refused while a live agent configuration cites it) | toggle back | ✔ | | `system_prompt.archive` | mod:hr |

## Estate: buildings, offices & desks (and the task queue)

Screens:

| Screen id | URL | When the user wants… |
| --- | --- | --- |
| `locations-list` | `/locations/` | Work Locations: the whole estate — every building, the offices inside each, desks, who's online, and the sites the business trades from (params: `kind`, `parent`, `online`) |
| `location-add` | `/locations/new` | to add a building, an office (VM) or a desk (params: `kind`, `parent`) |
| `location-edit` | `/locations/{id}/edit` | to edit a location's name, parent, description or specs |
| `location-view` | `/locations/{id}` | one location: specs, residents, office manager, applications, departments, queue |
| `location-tasks` | `/locations/tasks` | cross-location tasks (params: `mine`, `target`, `status`) |
| `location-task-add` | `/locations/tasks/new` | to ask another location to do something (params: `target`, `task_type`) |
| `location-task-view` | `/locations/tasks/{id}` | one task's status and result |
| `desk-permissions` | `/locations/{id}/permissions` | who may send tasks to a desk |

Actions (base `/locations/`):

| Action | File | Params | Undo | Confirm | Agent approval | Log | Who |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `location_task_create` | `tasks/save.php` | **target_location**, **title**, **instructions**, task_type, input refs, priority | cancel while queued | | | `location_task.create` | insider |
| `location_task_cancel` | `tasks/cancel.php` | **location_task** (queued or delivered) | — | | | `location_task.cancel` | own (requester), mod:locations |
| `location_task_retry` | `tasks/retry.php` | **location_task** (failed) | cancel the retry | | | `location_task.retry` | own, mod:locations |
| `location_task_decide_consent` | `tasks/consent.php` | **location_task**, **decision** (allow_once/allow_always/refuse) | — | | | `location_task.consent` | desk owner |
| `consent_grant_create` | `permissions/save.php` | **desk**, grantee_member or grantee_location, task_type, scope, expires_at | revoke | | | `consent_grant.create` | desk owner |
| `consent_grant_revoke` | `permissions/revoke.php` | **consent_grant** | grant again | | | `consent_grant.revoke` | desk owner, super |
| `location_set_office_manager` | `office-manager.php` | **location**, **agent** | restore prior | | | `location.set_office_manager` | mod:locations |
| `location_add_resident` | `resident-add.php` | **location**, **member** (human or agent), is_primary | remove | | | `location_resident.create` | mod:locations |
| `location_remove_resident` | `resident-remove.php` | **location**, **member** | add back | | | `location_resident.remove` | mod:locations |
| `location_save` | `save.php` | **name**, **kind** (building/office/desk/site — a site is a place the business trades from: address and timezone only), parent_location_id, siting (onsite/offsite — required for an office or desk), description, owner_member_id (desks), platform, external_ref, hostname, ip_address, cpu_cores, memory_mb, storage_gb, is_always_on, address (sites), timezone (sites — an IANA name), location | restore prior / delete new | | | `location.save` | mod:locations |
| `location_move` | `move.php` | **location**, **parent_location** (an office moving to another building — never a site) | move back | | | `location.move` | mod:locations |
| `location_rename` | `rename.php` | **location**, **name** | restore prior | | | `location.rename` | desk owner, admin |
| `location_add_department` | `department-add.php` | **location** (an office), **department** | remove | | | `department.set_home_location` | mod:locations, admin |
| `location_remove_department` | `/locations/department-remove.php` | **location**, **department** | add it back | | | `department.set_home_location` | mod:locations, admin |
| `location_retire` | `retire.php` | **location** (revokes the desk's token) | — | ✔ | | `location.retire` | desk owner, super |
| `location_delete` | `delete.php` | **location** (only one nothing points at) | — | ✔ | | `location.delete` | super |

Desk enrollment happens in the desktop app's sign-in flow (screen only, Phase 6). A building or office is never retired while it still has active children, applications or resident members; the endpoint refuses and names them.

Retire and delete are different remedies. **Retire** ends a location's working life and keeps it: the row, its specs and everything that happened there stay readable. **Delete** is for a location that should never have existed, and the super-admin alone may do it — refused, by name, the moment anything still points at it (locations inside it, residents, departments homed there, applications, agents, duties, runs, prompt-ledger entries, tasks, documents, employment profiles, stock locations). The activity trail survives either way: `activity_log` holds no foreign key to `locations`, and `location.delete` records what the location was.

## Applications

Screens:

| Screen id | URL | When the user wants… |
| --- | --- | --- |
| `applications-list` | `/applications/` | the inventory: every application the business could run, by business area, what runs highlighted (params: `area`, `department`, `health`, `gaps`, `active`, `retired`) |
| `application-add` | `/applications/new` | to register an application (params: `category`, `location`, `department`) |
| `application-view` | `/applications/{id}` | one application: office, super, endpoints, access, the sites or departments it serves and its roles, expertise (its expert agent and skills), cost, health (params: `tab`) |
| `application-edit` | `/applications/{id}/edit` | to edit an application's details, office, owner or cost link |
| `application-endpoint-add` | `/applications/endpoints/new?application={id}` | to add an endpoint agents or people use to reach it |
| `application-endpoint-edit` | `/applications/endpoints/{id}/edit` | to edit an endpoint or point it at a different secret |
| `application-access` | `/applications/access?application={id}` | who and which departments may use it, at what capability |

Actions (base `/applications/`):

| Action | File | Params | Undo | Confirm | Agent approval | Log | Who |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `application_save` | `save.php` | **name**, **app_key**, **category**, description, vendor, is_self_hosted, location, owner_department, owner_member, url, sso_path, sso_logout_path, directory_writes, scope_kind (none/location/department — what one installation serves; frozen while it has scopes or grants), version, criticality, notes, business_area_id, catalog_key (an outside product of the application catalog - on create only), application | restore prior / delete new | | | `application.save` | mod:applications |
| `application_set_status` | `status.php` | **application**, **status** (planned/active/degraded/retired) | restore prior | ✔ (retire) | | `application.set_status` | mod:applications |
| `application_token_mint` | `token-mint.php` | **application** | revoke | | | `application.token_mint` | super |
| `application_token_revoke` | `token-revoke.php` | **application** | mint again | ✔ | | `application.token_revoke` | super |
| `application_catalog_save` | `catalog-save.php` | **catalog_key**, **name**, **business_area**, **kind** (ours/external), description, icon, category, vendor | remove the entry | | | `application_catalog.save` | super |
| `application_endpoint_save` | `endpoints/save.php` | **application**, **name**, **kind**, url, auth_kind, secret (by name; the value is never shown or logged), agent_reachable, mcp_surface_version, notes, endpoint | restore prior / delete new | | | `application_endpoint.save` | mod:applications |
| `application_endpoint_remove` | `endpoints/remove.php` | **endpoint**, **application** | add back | ✔ | | `application_endpoint.remove` | mod:applications |
| `application_access_grant` | `access-grant.php` | **application**, member or **department** or residents (a site or office — everyone residing there), capability (read/write/admin — ignored when the application has roles), scope (the site or department on a scoped application), roles[] (the application's own roles - several allowed; the grant amounts to the highest), expires_at, note | revoke | | | `application_access.grant` | super |
| `application_access_revoke` | `access-revoke.php` | **application**, **application_access** | grant again | ✔ | | `application_access.revoke` | super |
| `application_access_change` | `access-change.php` | **application**, **application_access**, roles[] (the application's own roles - the whole new set), capability (read/write/admin — on an application without roles) | change it back | | | `application_access.change` | super |
| `application_roles_set` | `roles-set.php` | **application**, **roles** (by hand - only for an application that does not publish its roles; a JSON list of objects with key/name/capability/is_admin — exactly one is_admin; an empty list removes them all) | set the prior list | | never delegable to agents | `application.roles_set` | super |
| `application_roles_refresh` | `roles-refresh.php` | **application** | refresh again | | never delegable to agents | `application.roles_refresh` | super |
| `application_scope_add` | `scope-add.php` | **application**, location (a site — on an application scoped by location), department (on one scoped by department) | remove it | | | `application_scope.add` | mod:applications |
| `application_scope_remove` | `scope-remove.php` | **application**, **scope** (every live grant on it is revoked) | add it back and grant again | ✔ | | `application_scope.remove` | mod:applications |
| `application_sme_set` | `sme-set.php` | agent (an active agent - omit to clear the expert), **application** | set the prior expert | | | `application.sme_set` | mod:applications |
| `application_health_check` | `health-check.php` | **application** (runs the check now) | — | | | `application.health_check` | insider |

An application's credential is a reference to a tenant secret: the action stores the reference, and no screen, view, tool or log row ever carries the value. An agent reaching an application needs a live `application_access` row as well as its tool grants — granting an agent access to an application is itself a logged action.

## Approvals

Screens:

| Screen id | URL | When the user wants… |
| --- | --- | --- |
| `approvals` | `/approvals/` | what waits for their approval, or requests they made (params: `role`, `status`) |
| `approval-view` | `/approvals/{id}` | one request: the action, parameters, amount, requester, the agent run behind it |
| `approval-policies-settings` | `/settings/approval-policies` | which actions need approval, for whom, above what amount |
| `approval-policy-add` | `/settings/approval-policies/new` | to add a policy |
| `approval-policy-edit` | `/settings/approval-policies/{id}/edit` | to edit a policy |

Actions (base `/approvals/`):

| Action | File | Params | Undo | Confirm | Agent approval | Log | Who |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `approval_approve` | `approve.php` | **approval_request**, note (then runs the stored action) | — | ✔ | never delegable to agents | `approval_request.approve` | the approver |
| `approval_reject` | `reject.php` | **approval_request**, **reason** | — | | | `approval_request.reject` | the approver |
| `approval_cancel` | `cancel.php` | **approval_request** | — | | | `approval_request.cancel` | the requester |
| `approval_policy_save` | `/settings/approval-policies/save.php` | **name**, **category**, **action_pattern**, applies_to, agent, department, amount_threshold, currency, approver, expires_after_hours, policy | restore prior / delete new | ✔ | | `approval_policy.save` | super |
| `approval_policy_set_active` | `/settings/approval-policies/active.php` | **policy**, **active** | toggle back | ✔ | | `approval_policy.set_active` | super |
| `approval_policy_delete` | `/settings/approval-policies/delete.php` | **policy** | — | ✔ | delete | `approval_policy.delete` | super |

Approving is never available to an agent: the endpoint refuses when the acting member is an agent, whatever its grants.

## AI: prompt log, models & evals

Screens:

| Screen id | URL | When the user wants… |
| --- | --- | --- |
| `prompt-log` | `/ai/prompt-log` | model calls (params: `agent`, `status`, `request_id`, `run`, `period`) |
| `prompt-log-view` | `/ai/prompt-log/{id}` | one call's full prompt and response |
| `agent-run-view` | `/ai/runs/{id}` | one agent run: calls, actions, cost |
| `ai-spend` | `/ai/spend` | AI cost, tokens, latency and cache savings (params: `period`, `group_by`) |
| `ai-statements` | `/ai/spend/statements` | the ledger's period statements (A5): each month open or closed, its lines per provider, model, department, agent and application; download as CSV or JSON (params: `period`) |
| `models-settings` | `/settings/models` | the model registry and harnesses |
| `model-add` | `/settings/models/new` | to register a model |
| `model-edit` | `/settings/models/{id}/edit` | to edit a model's prices or status |
| `eval-sets` | `/ai/evals` | eval sets per agent or role |
| `eval-set-add` | `/ai/evals/new` | to create an eval set (params: `agent`, `role`) |
| `eval-set-view` | `/ai/evals/{id}` | one eval set: cases, runs, trend |
| `eval-case-add` | `/ai/evals/{id}/cases/new` | to write an eval case (params: `from_ledger`, `from_run`) |
| `eval-case-edit` | `/ai/evals/cases/{id}/edit` | to edit an eval case |
| `eval-run-view` | `/ai/evals/runs/{id}` | one eval run's per-case results |
| `audit` | `/ai/audit` | what the Auditor found: findings on agent work, open eval alerts, graded real runs — in shadow, what it would have done |
| `system` | `/ai/system` | the Sysadmin's view of the server: health probes, open events from the logs and guardrails (redacted), its recent decisions (params: `status`) |
| `graded-traces` | `/ai/evals/traces` | production traces graded by continuous evals (params: `agent`, `failed`) |
| `ai-usage-postings` | `/ai/spend/postings` | AI spend posted to the books per period, and what is still unposted (params: `period`, `status`) |
| `eval-watch` | `/ai/evals/watch` | the Audit department's watch: standing schedules and open degradation alerts (params: `agent`, `severity`, `status`) |
| `eval-schedule-add` | `/ai/evals/{id}/schedule` | to put an eval set on a standing schedule |
| `eval-alert-view` | `/ai/evals/alerts/{id}` | one alert: scores against baseline, the run behind it, what was done |

Actions (base `/ai/`):

| Action | File | Params | Undo | Confirm | Agent approval | Log | Who |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ai_period_rollup` | `spend/rollup.php` | **period** (YYYY-MM) | roll up again | | | `ai_period.rollup` | mod:ledger |
| `ai_period_close` | `spend/close.php` | **period** (YYYY-MM), note | none — a closed month stays closed | ✔ | | `ai_period.close` | super |
| `model_save` | `/settings/models/save.php` | **model_key**, **display_name**, **provider**, **provider_model_id**, **harness**, endpoint_url, context_window_tokens, prices, status, model (API key screen only) | restore prior / delete new | ✔ | | `model.save` | super |
| `model_set_status` | `/settings/models/status.php` | **model**, **status** | restore prior | ✔ | | `model.set_status` | super |
| `eval_set_save` | `evals/save.php` | **name**, agent or role_key, department, pass_threshold, description, status (draft/active/retired), trace_checks (a JSON list of JEV checks the Auditor applies to sampled real runs — empty clears them), eval_set | restore prior / delete new | | | `eval_set.save` | mod:evals |
| `eval_case_save` | `evals/case-save.php` | **eval_set**, **title**, **input**, expected, rubric, grader (jev/rubric_llm/exact/programmatic/human — jev is the default), checks (a JSON list of JEV checks — required when grader is jev), weight, eval_case | restore prior / delete new | | | `eval_case.save` | mod:evals |
| `eval_case_draft_checks` | `evals/draft-checks.php` | eval_case, rubric (one property per line — a draft of JEV checks is returned and nothing is saved) | — | | | `eval_case.draft_checks` | mod:evals |
| `eval_case_promote_trace` | `evals/promote.php` | **ledger_entry** or **agent_run**, **eval_set**, title, rubric | delete the case | | | `eval_case.promote` | mod:evals, agent's manager |
| `eval_case_set_active` | `evals/case-active.php` | **eval_case**, **active** | toggle back | | | `eval_case.set_active` | mod:evals |
| `eval_run_start` | `evals/run.php` | **eval_set**, agent, config_version (defaults to the active one — naming another weighs a change before it goes live), trigger (manual/change_control/hiring) | cancel while queued | | | `eval_run.start` | mod:evals, agent's manager |
| `eval_result_grade` | `evals/grade.php` | **eval_result**, **passed**, score, notes (a human-graded case, a JEV case JEV was unsure of, or a spot-check of any JEV grade) | restore prior grade | | | `eval_result.grade` | mod:evals (humans only) |
| `eval_schedule_save` | `evals/schedule-save.php` | **eval_set**, **kind** (scheduled_run/trace_sampling), **cadence**, sample_size, regression_delta, active, schedule | restore prior / delete new | | | `eval_schedule.save` | mod:evals |
| `system_event_set_status` | `/ai/system/event-status.php` | **event**, **status** (open/acknowledged/resolved/muted), note | set the prior status | | | `system_event.set_status` | super, admin |
| `system_one_set_mode` | `/agents/system-one-mode.php` | **agent** (a system_one agent), **mode** (shadow/live) | set the other mode | ✔ | never delegable to agents | `agent.system_one_mode` | super |
| `eval_alert_acknowledge` | `evals/alert-ack.php` | **eval_alert**, note | un-acknowledge | | | `eval_alert.acknowledge` | mod:evals, agent's manager |
| `eval_alert_resolve` | `evals/alert-resolve.php` | **eval_alert**, **resolution** | reopen | | | `eval_alert.resolve` | mod:evals, agent's manager |
| `run_verdict_set` | `verdict.php` | **run** or **call** (exactly one), **verdict** (good or bad), note | say it again to change it | | | `run_verdict.set` | whoever may see the run (humans only) |

Agents can't reach eval authoring or grading. The endpoints refuse agent callers, matching the read-side rule that agents never see eval cases.

## Memory & skills *(approved 2026-09-19 — stage H1 of `docs/hermes-integration-plan.md`; built in H4 and H5)*

Shared memory and shared skills live in MaluDB. Reads go through the Memory MCP server; **writes are these actions**, through PHP like every other change, so the gate, `log_activity()` and `check_approval()` all apply. An agent never holds a MaluDB token.

Actions (base `/`):

| Action | File | Params | Undo | Confirm | Agent approval | Log | Who |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `memory_remember` | `memory/remember.php` | **text**, **subject** (what it is about: one customer or vendor or process), scope (self/department/org; default self), department | supersede the note | | department and org scope | `memory.remember` | any insider; agents: own scope free, wider scope by approval |
| `core_memory_set` | `memory/core-set.php` | **key**, **value**, member (default: caller) | restore prior (superseded, never overwritten) | | | `memory.core_set` | the member itself, its manager, mod:hr |
| `skill_propose` | `skills/propose.php` | **agent_run**, **skill_name**, **bundle** | withdraw | | always — the manager reads the diff | `skill.propose` | the runner, for the run's agent |
| `skill_proposal_decide` | `skills/decide.php` | **skill_proposal**, **decision**, note | — | ✔ | never delegable to agents | `skill.approve` / `skill.reject` | the agent's manager, mod:hr |
| `skill_assign` | `skills/assign.php` | **skill_name**, **scope_kind** (org/department/role/agent/application), department, role_key, agent, application, pinned_bundle_hash | revoke | | never delegable to agents | `skill.assign` | mod:hr; dept-admin within their departments; mod:applications for an application |
| `skill_unassign` | `skills/unassign.php` | **skill_assignment** | assign again | ✔ | never delegable to agents | `skill.unassign` | mod:hr; dept-admin within their departments; mod:applications for an application |
| `skill_save` | `ai/skills/save.php` | **name**, **description**, **body** (the instructions: SKILL.md after its frontmatter), files[] (reference files - each a path and its text) | enable the previous version | | never delegable to agents | `skill.save` | super |
| `skill_set_enabled` | `ai/skills/enabled.php` | **name**, **skill** (the version's id), **enabled** (1 or 0) | set it back | | never delegable to agents | `skill.set_enabled` | super |

The library itself — every skill, its versions, its text and files — is AI Ops → **Skills** (`/ai/skills`, screens `skills-library`, `skills-library-view`, `skills-library-form`; 2026-09-27). A save never edits a version: a changed bundle becomes a new version, the old ones kept. Agents READ the library through two Records MCP tools, when granted: `skill_library` (the enabled skills, their descriptions and files) and `skill_read` (a skill's full SKILL.md or one reference file, newest enabled version) — what a Claude-harness agent's persona cuts off after 6,000 characters, and the reference files it has no other way to open.

## Written by the system, not by actions

These tables change only through webhooks, scheduled jobs or the agent runtime, never through a person, the command bar or an agent's action call. Each writer still logs to `activity_log` (sources `webhook`, `cron`, `agent`).

| Writer | Tables |
| --- | --- |
| Payment provider webhooks | `provider_events`, `provider_payments`, `payouts`, `disputes`, online `payments` and their allocations, `payment_links` status |
| MaluMail webhooks + mail sender | `email_messages`, `email_suppressions` (bounce/complaint), `digest_sends`, `notifications.email_sent_at` |
| Agent runtime (harness) | `agent_runs`, `prompt_ledger`, `prompt_payloads` |
| Eval runner | `eval_runs` progress, `eval_results` (non-human graders), `trace_grades`, `eval_alerts` raised by a schedule, `eval_schedules.next_run_at` |
| Invoice send / void / credit in full (inside those actions) | `stock_movements` of kind `sale` and `return`, `stock_levels` — logged as `stock_movement.sale` / `stock_movement.return` on the invoice |
| Approval endpoints (inside other actions) | `approval_requests` creation, `hr_events` |
| Scheduled jobs | recurring expense instances, duty runs (`agent_duties.next_run_at`), SLA due stamps, payload archival, backups, export expiry, desk presence, `desk_imports` expiry, location presence and `last_seen_at`, `applications.health_status` from scheduled checks, draft `ai_usage_postings` roll-ups awaiting posting |
| Connectors (Phase 4) | `content_metrics` pulls, `channels` connection status, `content_variants` publish results |
| Mail sync | `mail_threads`, `mail_messages`, `mail_attachments` for inbound mail; `mailboxes.last_sync_at` and sync errors; rule effects — logged as `mail_message.receive` (source `cron`), and `ticket.create` when a rule or the mailbox opens a ticket; an attachment download logs `mail_attachment.download` |
| Bank feeds and imports | `bank_transactions` rows and their import batch; `bank_accounts.last_synced_at` |
| Posting engine | `journal_entries` and `journal_lines` written from invoices, payments, expenses, AI usage, pay runs and stock movements; `ai_usage_postings.journal_entry_id` |
| Stock engine | `stock_levels` recalculated from `stock_movements`; reorder-point notifications |
| Signing page (`/sign/{token}` — no login; the private link is the authority) | `signature_signers` status, typed name, consent, drawn signature, address and browser; `signature_events`; the request's status; on completion the executed copy as a new `documents` row — logged as `signature_signer.view` / `.sign` / `.decline`, `signature_request.complete` and `document.create` with no actor |
| Signature provider webhooks | `signature_requests` status, `signature_signers` status and timestamps, `signature_events`, the executed document |
| Public form endpoint | `form_submissions` and the contact, ticket or deal a submission creates (an appointment is never booked automatically); `forms.submission_count` — logged as `form_submission.create` (source `portal`) plus the created record's own event; a filled honeypot is stored as `spam` and creates nothing |
| Report scheduler | `report_runs` from schedules, `report_schedules.next_run_at` — logged as `report_schedule.deliver` (source `cron`); a LINK is mailed and no export document is made |

## Voice coverage (spot checks)

| Utterance | Resolves to |
| --- | --- |
| "take me to Acme" | `find_screen` → `navigate(organization-view, {id})` |
| "add a deal for Acme, website redesign, twelve thousand, closing end of October" | `deal_create` |
| "move the Acme deal to proposal" | `deal_move_stage` |
| "I just talked to Maria at Beta about the renewal, she wants a quote by Friday" | `interaction_log` + `task_create` |
| "invoice Acme for the redesign hours this month and send it" | `invoice_create` → `invoice_add_unbilled` → `invoice_send` (confirm) |
| "they paid twelve hundred by check today" (on an invoice) | `payment_record` (invoice from screen context) |
| "log a forty dollar lunch with the Acme team, billable" | `expense_create` |
| "remind Acme about invoice forty two" | `invoice_send_reminder` (confirm) |
| "assign the homepage task to Sam, due Thursday" | `task_assign` + `task_reschedule` |
| "book a two hour site visit at Beta next Tuesday at ten with Olive" | `appointment_create` |
| "reply to this ticket saying the fix ships Monday" | `ticket_reply` (confirm) |
| "log forty five minutes on the Acme project" / "start a timer on Beta support" | `time_log` / `timer_start` |
| "schedule the launch post for LinkedIn Monday at nine" | `content_schedule` |
| "give the accountant read access to sales" | `module_grant_set` |
| "change the support agent's budget to two hundred a month" | `agent_update_config` (new version; activation after evals) |
| "approve it" (on an approval) | `approval_approve` (confirm) |
| "ask Ed's desk to summarize the Q3 spreadsheet" | `location_task_create` |
| "turn this prompt into an eval case for the bookkeeper" (on a prompt-log entry) | `eval_case_promote_trace` |
| "undo that" | `undo_last` |

## Decisions for approval

1. **`find_screen` + `navigate` instead of one routing list.** 148 screens is far past the ~40 where a single `navigate` description classifies reliably, so the assistant searches first when the id isn't obvious. The actions server builds both from this manifest at startup.
2. **Enable mod_rewrite in the shell conversion (1.8)** so canonical URLs (`/invoices/42/edit`) are served directly. The fork's `form.php?id=` fallback is retired for new modules.
3. **One naming rule ties manifest, logs and approvals together.** Action `entity_verb` logs `entity.verb`, and approval policies match those events. `.delete` destroys a record and `.remove` detaches something.
4. **External sends confirm first, by voice too.** Emailing an invoice, replying to a customer or publishing a post can't be undone, so they join destructive actions in asking first. Creates and updates still execute immediately with Undo, as the locked policy says.
5. **Actions are approval-aware.** Every endpoint checks the active policies for the acting member. A match writes an approval request and returns `pending_approval` without executing; approval replays the stored call through the same endpoint.
6. **Some actions are screen-only:** file uploads, API keys and payment or channel credentials, 2FA, token display, desk enrollment. Secrets and raw files never pass through the assistant or an agent's context.
7. **Agent configuration changes only as versions.** `agent_update_config` writes a draft version and queues a change-control eval run. `agent_activate_version` refuses without a passing gating run, which keeps EV8 at zero. Agents can't approve, author evals or grade.
8. **18 default approval policies, active now** (`db/053`). They pause agents on refunds, credit notes, write-offs, bill payments, expenses over 250 (base currency), recurring expenses, any deletion, voids, and every external send. The thresholds question stays open; editing a policy is one screen.
9. **Cert-study screens and actions stay registered** in their own manifest until retirement. At the shell conversion the business dashboard takes `/`, and the cert-study screens leave the main navigation and the default `find_screen` results.

## Open points

Schema gaps found while writing this manifest are already closed: `db/054_timers_desk_imports.sql` (running timers, staged desk imports) and `db/047` (cancellable data exports).

1. **Agent ticket replies need approval by default.** That makes a support agent draft-only until someone lowers the policy for it. Confirm, or exempt replies on tickets the agent is assigned?
2. **Undo window:** `undo_last` currently has no time limit. Recommendation: 10 minutes or 5 later actions, whichever comes first, so "undo that" never reaches back into yesterday.
