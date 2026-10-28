# Business OS MCP Tool Surface

2026-09-17 · Edward Honour · **Draft for M1 review (build plan 1.5)**. Decisions 1, 2, 4 and 6 approved 2026-09-17.

> Contract: every question in `docs/business-os-questions.md` maps to a tool below (coverage index at the end). A question with no tool is unfinished design.
> Reads: the `mcp_*` views in `db/050_mcp_views_business.sql` and `db/052_mcp_audit_views.sql` (schema: `docs/business-os-schema.md`).
> Replaces nothing yet: the cert-study tools in `docs/mcp-tool-surface.md` keep running until those modules are retired.

## Summary

- **135 business tools:** 118 on the records server and 17 on the activity server. They cover all 292 questions; 291 go through these two servers and DC9 goes through the desk tools (Phase 6).
- **The tools add no access of their own.** They read only `mcp_*` views, so visibility is decided in SQL for every caller, human or agent. A tool never reveals whether a hidden record exists.
- **Most tools serve several questions** through filters, which keeps the list short enough for agents to choose well. Each caller's tool list is also filtered to what they can use (decision 2).

## Conventions (every tool)

- **Read-only.** Every tool has `readOnlyHint: true`, and the servers connect as `app_records_ro` / `app_activity_ro`. Writes happen only through the app and the actions server.
- **Inputs:** Pydantic v2 models with `extra="forbid"` and a constraint on every field, as in the existing servers.
    - **Ids** are integers. Tools that take a human description instead (a name, an invoice number) resolve it or say how to.
    - **Periods:** `period` accepts `today`, `this_week`, `last_week`, `this_month`, `last_month`, `this_quarter`, `last_quarter`, `ytd`, `last_12_months`, or explicit `from` / `to` ISO dates. Days and months use the business timezone and fiscal year start.
    - **Paging:** `limit` defaults to 25 (max 100), plus `offset`. Every list reply reports `truncated`.
- **Money** is always grouped by currency and never summed across currencies. Every amount carries its currency code.
- **Empty results** say "nothing found you can see" and never "not allowed", following the questions doc's rule for hidden records.
- **Errors are actionable:** "no organization matched 'acme'; try `find_contacts` with a shorter fragment".
- **Every call is logged** to `activity_log` as `mcp.tool_call`, with `source='mcp'`, the tool name, the arguments, the duration, and `entity_type='mcp_access_token'` pointing at the calling token (feeds A9, X7).
- **Gate** (last column below): which callers see the tool in their tool list.
    - A **module** gate means a super-admin, a dept-admin inside the departments they administer, or any member holding that module grant.
    - **admin** means a super-admin, or a dept-admin for rows in a department they administer (and for people they administer); **super** means super-admin only; **all** means anyone signed in; **insider** excludes external members.
    - Agents additionally need a live `agent_tool_grants` row for the tool.
    - The view still decides the rows, so a gate only trims the list.

## Records server — `maludb_os_records_mcp` (role `app_records_ro`)

### Team & access

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `team_directory` | Someone asks who works here, in which role or department, human or AI | A1, H1 | `mcp_team_directory`, `mcp_departments` | `q?`, `department_id?`, `member_kind?`, `business_role?` | insider |
| `member_access` | Someone asks what a person or agent can reach | A2 | `mcp_team_directory`, `mcp_module_grants`, `mcp_record_shares`, `mcp_department_members` | `member_id` | admin |
| `team_invitations` | Pending invites, or who invited someone | A3, A10 | `mcp_business_invitations`, `mcp_team_directory` | `status?` (pending/all) | admin |
| `security_overview` | 2FA gaps, MCP tokens in use, connected AI clients | A4, A5, X7 | `mcp_team_directory`, `mcp_token_list` | `member_id?` | all (own tokens); owner (everyone) |
| `external_access` | Who outside the business can see what | A6, C16, DC5 | `mcp_record_shares`, `mcp_module_grants`, `mcp_team_directory` | `member_id?`, `entity_type?`, `entity_id?` | admin |
| `departments` | Department list, managers, headcount, which department does each standing duty (Front Office, HR, Accounting, Audit), who a department reports to, the office it works in, its applications and budget vs actual, departments with no manager or no members | H1, H11, H14, H15 | `mcp_departments`, `mcp_department_members`, `mcp_applications`, `mcp_ai_usage_postings` | `include_archived?`, `gaps_only?`, `system_key?`, `include_spend?` | insider |

### Contacts & CRM

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `find_contacts` | Looking up any person or company by name, email, phone or fragment; listing customers, vendors, leads or partners. Call before any tool that needs an organization or contact id | C1, C3 | `mcp_organizations`, `mcp_contacts` (trigram + full-text), `mcp_taggings` | `q?`, `kind?` (organization/person/both), `relationship_type?`, `tag?`, `owner_member_id?` | contacts |
| `get_organization` | The full picture of one company: main contact, people, deals, invoices, projects, tickets, recent interactions, owner | C2, C8, C9, C10 | `mcp_organizations`, `mcp_contacts`, `mcp_deals`, `mcp_invoices`, `mcp_projects`, `mcp_tickets`, `mcp_interactions` | `organization_id`, `interactions_limit?` | contacts |
| `get_contact` | One person: how to reach them, their organization, last conversations, owner | C1, C8, C10 | `mcp_contacts`, `mcp_interactions`, `mcp_deals` | `contact_id` | contacts |
| `get_deal` | One deal: stage, value, probability, close date, owner, interactions | C4, C10 | `mcp_deals`, `mcp_interactions` | `deal_id` | contacts |
| `pipeline` | Where open deals stand, what closes this month or quarter, what has gone quiet | C4, C5, C6, DB4 | `mcp_deals`, `mcp_pipelines` | `stage?`, `owner_member_id?`, `closing_period?`, `quiet_for_days?` (default business setting), `group_by?` (stage/owner/month) | contacts |
| `sales_performance` | Win rate and average deal size by stage, source or owner | C7 | `mcp_deals` | `period`, `group_by` (source/owner/stage) | contacts |
| `contact_hygiene` | Contacts with no owner or probable duplicates | C11 | `mcp_organizations`, `mcp_contacts` | `check` (no_owner/duplicates/both), `similarity?` (default 0.6) | contacts |
| `lead_sources` | Where leads and deals came from, including campaigns and content | C12, SM8, SM11 | `mcp_organizations`, `mcp_contacts`, `mcp_deals`, `mcp_campaigns`, `mcp_content_items` | `period`, `group_by` (source/campaign/content_item), `won_only?` | contacts |

### Sales & invoicing

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `find_invoices` | Listing invoices by status, customer, project, deal, number, or who created them (human or agent) | S3, S10, S14, S20 | `mcp_invoices` | `status?`, `organization_id?`, `project_id?`, `deal_id?`, `number?`, `overdue?`, `created_by_kind?`, `payment_source?`, `period?` | sales |
| `get_invoice` | One invoice with lines, payments, credits, payment links (opened / completed times) | S3, S21 | `mcp_invoices`, `mcp_invoice_lines`, `mcp_payment_allocations`, `mcp_credit_notes`, `mcp_payment_links` | `invoice_id` or `number` | sales |
| `receivables_aging` | Who owes us and how overdue (0–30, 31–60, 61–90, 90+), plus average days to pay | S2, S11 | `mcp_invoices`, `mcp_payment_allocations`, `mcp_payments` | `organization_id?`, `as_of?`, `include_days_to_pay?` | sales |
| `revenue_summary` | Invoiced, collected or tax charged over a period, by month, customer, tax rate or payment source; top customers | S1, S4, S7, S9, S20 | `mcp_invoices`, `mcp_invoice_lines`, `mcp_payments` | `metric` (invoiced/collected/tax), `period`, `group_by?` (month/customer/tax_rate/payment_source), `top?` | sales |
| `customer_statement` | A customer's statement: invoices, payments, credits, running balance | S8 | `mcp_invoices`, `mcp_payments`, `mcp_payment_allocations`, `mcp_credit_notes` | `organization_id`, `period?` | sales |
| `quotes_pipeline` | Outstanding and expired quotes; quote-to-invoice conversion rate | S5, S6 | `mcp_quotes` | `status?`, `period?`, `include_conversion?` | sales |
| `online_payments` | Failed online payments; payment links unpaid after N days | S15, S16 | `mcp_provider_payments`, `mcp_payment_links`, `mcp_invoices` | `view` (failed/stale_links), `older_than_days?`, `period?` | sales |
| `refunds_and_disputes` | Open refunds and disputes, amount at stake, who requested a refund and its approval | S17, S22 | `mcp_refunds`, `mcp_disputes`, `mcp_approval_requests` | `status?`, `refund_id?` | sales |
| `payment_reconciliation` | Payouts and provider fees; provider payments with no invoice, unallocated or duplicate payments | S18, S19 | `mcp_payouts`, `mcp_provider_payments`, `mcp_payments`, `mcp_payment_allocations` | `view` (payouts/unmatched), `period?` | sales |

### Expenses & cost

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `spend_summary` | Spend over a period by category, vendor or month; spend on X; this month vs the 3-month average | E1, E2, E3, E9 | `mcp_expenses`, `mcp_expense_categories` | `period`, `group_by?` (category/vendor/month), `q?`, `category_id?`, `vendor_organization_id?`, `compare_to_average_months?` | expenses |
| `find_expenses` | Listing expenses: missing receipts, my submissions and their status, matching text | E2, E5, E10 | `mcp_expenses` | `missing_receipt?`, `submitted_by_me?`, `status?`, `q?`, `period?` | expenses (own submissions: all) |
| `bills_due` | Bills due in the next N days | E4 | `mcp_expenses` | `within_days?` (default 14) | expenses |
| `recurring_costs` | Subscriptions, rent and other recurring costs per month | E6 | `mcp_recurring_expenses` | `active_only?` | expenses |
| `cost_breakdown` | What a project, customer or campaign cost: expenses, hours × rate, AI spend, billable share, budget used | E7, P8, P13, W6, SM11 | `mcp_expenses`, `mcp_time_entries`, `mcp_agent_runs`, `mcp_projects`, `mcp_campaigns` | `scope` (project/customer/campaign), `id`, `period?`, `detail?` (by agent/task) | projects or expenses |
| `unbilled_work` | Billable work not invoiced yet: completed jobs, hours, billable expenses, per customer | E8, K7, W3 | `mcp_appointments`, `mcp_time_entries`, `mcp_expenses` | `organization_id?`, `kinds?` (jobs/hours/expenses) | sales |
| `accountant_export_status` | What went into the accountant export for a period and when it was last pulled | E13 | `mcp_accountant_exports` | `period?` | expenses |

### Projects & tasks

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `my_work` | "What's on my plate / needs my attention": the caller's tasks, today's appointments, assigned tickets, approvals waiting, overdue invoices they own, and for agents their duties and remaining budget | P2, K2, T2, H9, DB2 | `mcp_tasks`, `mcp_appointments`, `mcp_tickets`, `mcp_approval_requests`, `mcp_invoices`, `mcp_agent_duties`, `mcp_agents`, `mcp_agent_runs` | `horizon_days?` (default 7) | all |
| `find_projects` | Active projects, for whom, on track or over budget | P1, P8 | `mcp_projects`, `mcp_time_entries`, `mcp_expenses`, `mcp_agent_runs` | `status?`, `organization_id?`, `department_id?`, `over_budget?` | projects |
| `get_project` | One project: team and what each is doing, progress, blockers, milestones | P4, P5, P6, P9 | `mcp_projects`, `mcp_project_members`, `mcp_tasks`, `mcp_task_dependencies`, `mcp_milestones` | `project_id` | projects |
| `find_tasks` | Tasks by assignee, project, department, status; overdue, blocked, or assigned to agents | P3, P5, P7 | `mcp_tasks`, `mcp_task_dependencies` | `assignee_member_id?`, `assignee_kind?`, `project_id?`, `department_id?`, `status?`, `overdue?`, `blocked?` | projects (own tasks: all) |
| `upcoming_milestones` | Milestones due in the next N days across projects | P9 | `mcp_milestones` | `within_days?` (default 14) | projects |
| `team_workload` | How busy people are: booked hours, open tasks, appointments per person | DB5, K1 | `mcp_tasks`, `mcp_appointments`, `mcp_team_directory` | `period?` (default this_week), `department_id?` | admin |

### Scheduling

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `schedule` | What's happening in a window, for a person or customer, and the next appointment with someone | K1, K2, K4, K8 | `mcp_appointments`, `mcp_appointment_assignees` | `period?`, `member_id?`, `organization_id?`, `appointment_type_id?`, `next_only?` | scheduling (own: all) |
| `find_free_time` | Who is free for a job of a given length in a window | K3 | `mcp_busy_blocks`, `mcp_team_directory` | `duration_minutes`, `from`, `to`, `member_ids?`, `department_id?`, `resource_id?` | scheduling |
| `schedule_conflicts` | Double-bookings of people or resources | K5 | `mcp_busy_blocks` | `period?`, `member_id?`, `resource_id?` | scheduling |
| `job_counts` | How many jobs of each type in a period | K6 | `mcp_appointments` | `period`, `status?` (default completed) | scheduling |

### Tickets

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `find_tickets` | Open tickets by department, assignee, priority or customer; unreplied; mine; my requests (portal) | T1, T2, T4, T5, T9 | `mcp_tickets` | `status?`, `department_id?`, `assignee_member_id?`, `priority?`, `organization_id?`, `unreplied?`, `requested_by_me?` | tickets (own requests: all) |
| `get_ticket` | One ticket with its thread (External callers never receive internal notes) | T9 | `mcp_tickets`, `mcp_ticket_messages` | `ticket_id` or `number` | tickets (own requests: all) |
| `sla_status` | Tickets breaching or close to breaching SLA | T3 | `mcp_tickets` | `within_minutes?` (default 60), `department_id?` | tickets |
| `similar_tickets` | "Have we seen this before and how was it fixed?" | T6 | `mcp_tickets`, `mcp_ticket_messages` (full-text) | `q`, `resolved_only?` (default true) | tickets |
| `ticket_metrics` | Common categories; first-response and resolution times by department; tickets agents resolved and reopen rates | T7, T8, T11 | `mcp_tickets`, `mcp_team_directory` | `period`, `group_by?` (category/department/assignee_kind) | tickets |

### Documents

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `find_documents` | Find a file, procedure or handbook by name or content; documents imported from desks | DC1, DC2, DC4, DC8 | `mcp_documents` (full-text), `mcp_folders` | `q?`, `kind?`, `department_id?`, `folder_id?`, `origin?` | documents |
| `get_document` | Read one document's body (procedure, handbook, page) and its version list | DC2, DC4 | `mcp_documents`, `mcp_document_versions` | `document_id` | documents |
| `record_documents` | Documents attached to a customer, project, invoice, ticket, expense or content item | DC3 | `mcp_document_links` | `entity_type`, `entity_id` | documents |
| `compare_document_versions` | What changed between two versions (returns both bodies and a line diff) | DC6 | `mcp_document_versions` | `document_id`, `from_version`, `to_version` | documents |

### Time

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `time_summary` | Where hours went by project, customer, person or day; my hours; utilization (billable ÷ total) | W1, W2, W5 | `mcp_time_entries` | `period`, `group_by` (project/customer/member/day), `member_id?`, `utilization?` | time (own: all) |
| `missing_timesheets` | Who hasn't logged time in a period | W4 | `mcp_time_entries`, `mcp_team_directory` | `period?` (default this_week), `department_id?` | time |

### Notifications

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `my_notifications` | What needs my attention, my latest digest, how my notifications are delivered | N1, N2, N3 | `mcp_my_notifications`, `mcp_my_digests`, `mcp_notification_preferences` | `view` (unread/digest/settings) | all |
| `email_deliverability` | Bounced or suppressed addresses; whether a person was emailed about something and opened it | N4, N5 | `mcp_email_messages`, `mcp_email_suppressions` | `view` (problems/suppressed/for_record), `member_id?`, `entity_type?`, `entity_id?` | admin (own mail: all) |

### Departments & agent HR

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `find_agents` | Which agents we employ, what each does, who manages them, and budget use this month | H2, H5 | `mcp_agents`, `mcp_agent_runs` | `department_id?`, `status?`, `near_budget_pct?` | insider |
| `agent_profile` | One agent's job description, model, tool grants, schedule, config history, and what it may do without approval. Agents call it on themselves | H3, H7, H10 | `mcp_agents`, `mcp_agent_config_versions`, `mcp_agent_tool_grants`, `mcp_agent_duties`, `mcp_approval_policies` | `agent_member_id?` (default: caller) | hr, the agent's manager, or the agent |
| `agent_conversations` | The caller's own chat threads with agents (agent page → Chat): which agent, title, turns, when. Private to the person | agent-chat | `mcp_agent_conversations` | `agent_member_id?`, `include_archived?` | own conversations only |
| `agent_conversation_read` | The turns of one of the caller's own chats, oldest first: what was said, the reply, state, cost, the run behind each | agent-chat | `mcp_agent_conversations`, `mcp_agent_runs` | `conversation_id`, `limit?` | own conversations only |
| `agent_performance` | How agents perform: tasks closed, tickets resolved, escalations (and what about), spend vs budget, eval scores, approvals needed. Pair with `activity_summary` for action counts | H4, H8, DB7 | `mcp_agents`, `mcp_tasks`, `mcp_tickets`, `mcp_agent_escalations`, `mcp_agent_runs`, `mcp_eval_runs`, `mcp_approval_requests` | `agent_member_id?`, `days` (default 30) | hr or manager |
| `hr_history` | Hire, suspend, offboard and other HR events for a person or agent | H12, H13 | `mcp_hr_events`, `mcp_performance_reviews` | `member_id`, `include_reviews?` | hr (own: all) |

### Estate: buildings, offices, desks & the task queue

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `estate` | The whole picture: buildings, the offices (VMs) inside each, the desks, and what runs where. The map an agent reads before it asks for anything | L11 | `mcp_locations`, `mcp_applications`, `mcp_location_residents` | `kind?`, `include_retired?`, `include_applications?` | insider |
| `locations` | Locations of one kind: which desks are online, which offices exist, last seen, app version | L1, L9 | `mcp_locations` | `kind?` (building/office/desk), `parent_location_id?`, `online_only?` | insider |
| `get_location` | One location: its specs (platform, host reference, hostname, address, CPU, memory, storage), its residents and office manager, the applications it hosts, its departments, queue counts | L2, L12 | `mcp_locations`, `mcp_location_residents`, `mcp_applications`, `mcp_departments`, `mcp_location_tasks` | `location_id` | insider |
| `who_is_where` | Where a person or agent works: the office an agent runs in, who is working remotely from a desk right now | L13 | `mcp_location_residents`, `mcp_locations`, `mcp_agents` | `member_id?`, `location_id?`, `online_only?` | insider |
| `find_location_tasks` | Status of tasks I sent; what's queued for my desk; failed or refused tasks and why; tasks that touched my desk | L3, L4, L5, L7 | `mcp_location_tasks` | `requested_by_me?`, `target_location_id?`, `status?`, `period?` | insider |
| `desk_permissions` | Who has standing permission to send tasks to a desk, and for what | L6 | `mcp_consent_grants` | `desk_location_id?` (default: caller's desk) | desk owner, super |
| `queue_metrics` | How long tasks wait in the queue, per location | L8 | `mcp_location_tasks` | `period`, `location_id?` | locations |
| `route_request` | Office manager only: which resident agent (by grants, duties and presence) should handle a request | L10 | `mcp_location_residents`, `mcp_agents`, `mcp_agent_tool_grants`, `mcp_agent_duties`, `mcp_locations` | `location_id`, `task_type`, `required_tools?` | office-manager agents, admin |

### Applications

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `find_applications` | What we run and where: by category, department or office; health; and the gaps — no owner, stale health check, missing or expiring credential | AC1, AC4 | `mcp_applications`, `mcp_application_endpoints` | `category?`, `department_id?`, `location_id?`, `health?`, `gaps_only?` | insider |
| `get_application` | One application: where it runs, who owns it, its endpoints (never the secret), who has access at what capability, and what it costs | AC1, AC3, AC5 | `mcp_applications`, `mcp_application_endpoints`, `mcp_application_access`, `mcp_recurring_expenses` | `application_id`, `include_access?` | insider (access list: applications module, manager, or a grantee) |
| `my_applications` | What I can reach and how — the first call an agent makes when a job needs an outside system | AC2 | `mcp_my_applications`, `mcp_application_endpoints` | `category?` | all (own grants) |
| `application_scopes` *(db/141)* | The sites or departments one installation of a scoped application serves, and on each who is granted which of the application's own roles (member, department, or everyone at a site) | AC7 | `mcp_application_scopes`, `mcp_application_access` | `application_id`, `scope_id?` | insider (grants gated as get_application's access) |
| `member_application_access` *(db/141)* | Every application and scope a member can use, with the role and the route (direct, department, residency) | AC8 | `mcp_application_access`, `mcp_department_members`, `mcp_location_residents` | `member_id`, `application_id?` | insider (gated as get_application's access) |
| `system_events` *(db/145)* | What is going wrong on the server: journal, Apache and PostgreSQL log events and the kernel's guardrail events, grouped, classified by JEV, redacted | SY1 | `mcp_system_events` | `status?`, `category?`, `min_severity?`, `source?`, `period?` | super, IT admin |
| `system_health` *(db/145)* | The last health probes: services, disk, memory, swap, backups, application health and versions | SY2 | `mcp_system_probes` | `only_problems?` | super, IT admin |
| `audit_findings` *(db/145)* | What the Auditor found about agents' work, and the open eval alerts | AU1 | `mcp_system_one_decisions`, `mcp_eval_alerts` | `period?`, `agent_member_id?` | super, Audit admin |
| `system_one_decisions` *(db/145)* | The decision trail of the system_one agents — in shadow, what they would have done | AU2 | `mcp_system_one_decisions` | `agent_member_id?`, `playbook?`, `decision?`, `mode?`, `period?` | super, the agent's department admin |

### Assets (added 2026-09-21, `mcp/business_assets.py`)

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `find_assets` | What the business owns and operates, physical and technical: by class, category, department, location, custodian, application, status; what is due | AS1–AS4 | `mcp_assets`, `mcp_asset_maintenance` | `asset_class?`, `category?`, `department_id?`, `location_id?`, `custodian_member_id?`, `application_id?`, `status?`, `include_gone?`, `due_within_days?`, `text?` | the view: mod:assets, dept-admin of the department, the custodian |
| `get_asset` | One asset in full: what it is, whose and where, what it runs on and what runs on it, every move, its maintenance (cost only for whoever may manage it) | AS2, AS5 | `mcp_assets`, `mcp_asset_movements`, `mcp_asset_maintenance` | `asset_id` | the view |
| `asset_summary` | The register in numbers by department, location, category or class; purchase cost where visible; how many have something due | AS6 | `mcp_assets` | `by?` | the view |

### Approvals

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `approval_queue` | What's waiting for my approval; status of requests I made | AP1, AP5 | `mcp_approval_requests` | `role` (approver/requester), `status?` | insider |
| `approval_policy` | Which actions need approval for an agent, department or action | AP2, H10 | `mcp_approval_policies` | `agent_member_id?`, `department_id?`, `action_key?` | insider |
| `approval_history` | What was approved or rejected, expired requests, decision times per approver, money-out requests by agents | AP3, AP4, AP6, E12 | `mcp_approval_requests` | `period`, `status?`, `decided_by?`, `category?`, `requested_by_kind?`, `group_by?` (approver) | approvals (own decisions: all) |

### Prompt ledger & runtime

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `ai_spend` | AI cost, tokens, latency and cache savings by agent, model, provider, location, project or day; what was posted to the books for a period, and whether the posting still reconciles to the ledger it came from | PL1, PL4, PL5, PL9, DB7, E14, E15 | `mcp_prompt_ledger`, `mcp_model_registry`, `mcp_ai_usage_postings` | `period`, `group_by` (agent/model/provider/location/project/department/day), `agent_member_id?`, `view?` (usage/postings/reconciliation) | ledger, expenses or agent's manager |
| `ledger_calls` | Individual model calls: failures, timeouts, rate limits; calls in a run or task | PL3, PL7 | `mcp_prompt_ledger`, `mcp_agent_runs` | `status?`, `agent_member_id?`, `agent_run_id?`, `task_id?`, `period?` | ledger or agent's manager |
| `prompt_for_request` | Show the full prompt and response behind an action. Get the `request_id` from the activity server's `record_history` first | PL2 | `mcp_prompt_ledger`, `mcp_prompt_payloads` | `request_id` | ledger, acting member, or agent's manager (agents: own calls only) |
| `model_catalog` | Which models are available, their harness and prices | PL6 | `mcp_model_registry` | `status?` | insider |
| `agent_runs` | What an agent is doing or did: runs by status, trigger, duty and cost; what is running right now across the organisation; the runs a delegation spawned | H4, DB7, PL7 | `mcp_agent_runs` | `agent_member_id?`, `status?`, `period?`, `parent_run_id?` | hr or agent's manager; agents: own runs |

### Shared memory & skills *(approved 2026-09-19 — a third read server, `maludb_os_memory_mcp`, port 8814; built in H4/H5)*

The Memory server holds the tenant's MaluDB token and enforces scope: a caller recalls its own memory, its departments' and the organisation's — never another member's. Writes are manifest actions, not tools.

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `recall` | What do we know about X — semantic and keyword recall over shared memory | new | MaluDB, scoped | `query`, `scope?` (self/department/org/all-visible), `limit?` | any insider; scope set = self + own departments + org |
| `core_memory` | An agent's or person's standing facts and preferences | new | MaluDB principal profile | `member_id?` (default caller) | self, manager, hr |
| `session_search` | What was said in earlier runs and chats | new | MaluDB chat sessions | `query`, `agent_member_id?`, `period?` | self, manager, hr |
| `skill_catalog` *(records server)* | Which skills exist, who has them, what is waiting for review | new | `mcp_skill_assignments`, `mcp_skill_proposals` | `agent_member_id?`, `status?` | hr, agent's manager; agents: own |

### Evaluations

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `eval_status` | Did a candidate pass hiring evals; an agent's score trend; did the last change regress, and on which cases | EV1, EV2, EV4 | `mcp_eval_runs`, `mcp_eval_results`, `mcp_eval_sets` | `agent_member_id?`, `eval_set_id?`, `trigger?`, `compare_to_baseline?` | evals or agent's manager (humans only) |
| `eval_findings` | Cases failing most; cases promoted from real traces and their ledger source; poorly graded production traces | EV3, EV5, EV6 | `mcp_eval_results`, `mcp_eval_cases`, `mcp_trace_grades` | `view` (failing_cases/promoted/graded_traces), `period?`, `agent_member_id?` | evals (humans only) |
| `eval_watch` | The Audit department's standing watch: which sets run on a schedule and when next, which agents are degrading (threshold breach, regression against baseline, trace drift), missed cycles and unacknowledged alerts. An agent calls it on itself to see whether it is slipping | EV9, EV10, EV11, EV12 | `mcp_eval_schedules`, `mcp_eval_alerts`, `mcp_eval_runs` | `agent_member_id?` (default: caller if an agent), `status?`, `severity?`, `period?` | evals or agent's manager; agents: own alerts |
| `ungated_deployments` | Audit: agent config versions activated without a passing eval run. Healthy answer is none | EV8 | `mcp_agent_config_versions`, `mcp_eval_runs` | `period?` | super |

### Content & social

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `content_calendar` | What's going out on which channels; channels with nothing scheduled in the next N days | SM1, SM7 | `mcp_content_variants`, `mcp_channels` | `period?` (default this_week), `channel_id?`, `gaps_within_days?` | content |
| `content_pipeline` | Drafts and items in review and who they wait on; agent-drafted items and approval state; failed publishes | SM2, SM3, SM4 | `mcp_content_items`, `mcp_content_variants`, `mcp_approval_requests` | `status?`, `author_kind?`, `failed_only?` | content |
| `content_performance` | How a campaign's posts perform; best posts by channel | SM5, SM6 | `mcp_content_metrics`, `mcp_content_variants`, `mcp_campaigns` | `campaign_id?`, `period?`, `channel_id?`, `top?`, `metric?` | content |
| `channel_health` | Connected channels and any expired or broken connection | SM9 | `mcp_channels` | — | content |
| `find_content` | Have we already posted about a topic, and when | SM10 | `mcp_content_items`, `mcp_content_variants` (full-text) | `q`, `published_only?` | content |
| `unapproved_publishing` | Audit: content published to a channel without the required approval. Healthy answer is none | SM13 | `mcp_content_variants`, `mcp_content_items`, `mcp_approval_requests`, `mcp_approval_policies` | `period?` | admin |

### Bookkeeping & the ledger

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `financial_statement` | Profit and loss, balance sheet or trial balance for a period, by account, with the comparison period | GL1, GL2, GL3 | `mcp_journal_lines`, `mcp_gl_accounts`, `mcp_fiscal_periods` | `statement` (pl/balance_sheet/trial_balance), `period`, `compare_to?`, `department_id?` | books |
| `account_activity` | One account's opening balance, movements and closing balance; what we owed and were owed at period end | GL4, GL11 | `mcp_journal_lines`, `mcp_gl_accounts` | `account` (code or id), `period`, `organization_id?` | books |
| `find_journal_entries` | Entries by period, status or source; what a specific invoice, payment or expense posted; what was reversed | GL5, GL6, GL12 | `mcp_journal_entries`, `mcp_journal_lines` | `period?`, `status?`, `source?`, `source_entity_type?`, `source_entity_id?` | books |
| `bank_status` | Unmatched bank transactions, the gap to the statement, and each account's reconciliation state | GL7, GL8 | `mcp_bank_transactions`, `mcp_bank_accounts`, `mcp_bank_reconciliations` | `bank_account_id?`, `period?`, `unmatched_only?` | books |
| `posting_rules` | Which document type or category posts to which accounts | GL9 | `mcp_gl_posting_rules`, `mcp_gl_accounts` | `source?` | books |
| `books_audit` | The bookkeeping audit set: closed and locked periods, changes to posted entries, and whether posted AI usage agrees with the prompt ledger. Healthy answers are "none" and "agrees" | GL10, GL13, GL14 | `mcp_fiscal_periods`, `mcp_journal_entries`, `mcp_ai_usage_postings`, `mcp_prompt_ledger` | `period?`, `check?` (periods/edits/ai_usage) | super, books |

### Shared inbox

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `find_mail_threads` | What is unanswered, mine, unassigned, or became a ticket or deal | IB1, IB2, IB4, IB6 | `mcp_mail_threads`, `mcp_mailboxes` | `mailbox_id?`, `status?`, `assigned_to_me?`, `unassigned?`, `unread_only?`, `became?` (ticket/deal/none) | inbox |
| `mail_thread` | One conversation in full: its messages in order, its attachments and what was filed | IB3, IB9 | `mcp_mail_messages`, `mcp_mail_attachments`, `mcp_mail_threads` | `mail_thread_id?`, `organization_id?` (everything from this customer) | inbox (own threads: all) |
| `search_mail` | Find the email where someone said something (full-text over subject, sender and body) | IB5 | `mcp_mail_messages` | `q`, `mailbox_id?`, `period?`, `direction?` | inbox |
| `mailbox_stats` | First-response times by mailbox and person, and what we sent out and whether it delivered | IB7, IB8 | `mcp_mail_threads`, `mcp_mail_messages`, `mcp_email_messages` | `period`, `group_by?` (mailbox/member) | admin, inbox |
| `mailbox_rules` | Mailboxes we receive on and the routing rules active on each | IB10 | `mcp_mailboxes`, `mcp_mail_rules` | `mailbox_id?` | inbox |

### People & payroll

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `find_people` | Employees and contractors, their department, manager, status, and who is starting or leaving | PE1, PE11 | `mcp_employment_profiles` | `status?`, `department_id?`, `employment_type?`, `starting_or_leaving?` | people, admin (own reports) |
| `employment_profile` | One person's employment details and pay, and how their pay has changed | PE2, PE5 | `mcp_employment_profiles`, `mcp_compensation_changes` | `member_id?` (default: caller) | own, people, the person's manager |
| `payroll_summary` | What people cost per period by department, one person's monthly cost, and pay against what their time was billed for | PE3, PE4, PE12 | `mcp_pay_run_items`, `mcp_pay_run_lines`, `mcp_pay_runs`, `mcp_time_entries` | `period`, `group_by?` (department/member), `member_id?` | super, people |
| `pay_runs` | What is in a pay run per person, what it posted, and which runs are unapproved or unpaid | PE6, PE7 | `mcp_pay_runs`, `mcp_pay_run_items`, `mcp_journal_entries` | `pay_run_id?`, `status?`, `period?` | super, people |
| `leave` | My remaining balance, what is waiting for my approval, and who is off in a date range | PE8, PE9, PE10 | `mcp_leave_balances`, `mcp_leave_requests`, `mcp_leave_types` | `view` (my_balance/pending/calendar), `period?`, `member_id?` | all (own); admin for people they administer |

### Products & inventory

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `find_products` | What we sell, at what price and cost, and which supplier we buy it from | IV1, IV10 | `mcp_products`, `mcp_organizations` | `q?`, `kind?`, `supplier_organization_id?`, `include_archived?` | insider (cost: inventory, super) |
| `stock_levels` | How much we have and where, what is below its reorder point, stock value by location, and count differences | IV2, IV3, IV6, IV11 | `mcp_stock_levels`, `mcp_stock_locations`, `mcp_products` | `product_id?`, `stock_location_id?`, `below_reorder_only?`, `valuation?` | insider (value: inventory) |
| `stock_movements` | What moved in or out, when, and against which document | IV5 | `mcp_stock_movements` | `product_id?`, `stock_location_id?`, `kind?`, `period` | inventory |
| `product_sales` | What sold this period and at what margin, and which quotes or invoices include a product | IV4, IV7 | `mcp_invoice_lines`, `mcp_quote_lines`, `mcp_products`, `mcp_stock_movements` | `period`, `product_id?`, `group_by?` (product/customer) | sales, inventory |
| `purchase_orders` | Open orders, expected dates, and what is still outstanding against each | IV8, IV9 | `mcp_purchase_orders`, `mcp_purchase_order_lines` | `status?`, `vendor_organization_id?`, `period?`, `outstanding_only?` | inventory |

### E-signature

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `find_signature_requests` | What is out for signature, who we are waiting on, what is expiring, and what was declined | SG1, SG2, SG3, SG5 | `mcp_signature_requests`, `mcp_signature_signers` | `status?`, `entity_type?`, `entity_id?`, `expiring_within_days?`, `organization_id?` | signatures, the record's module |
| `signature_audit` | One request's full trail — who viewed and signed, when and from where — where the executed copy is, and how long customers take | SG4, SG6, SG7 | `mcp_signature_events`, `mcp_signature_signers`, `mcp_signature_requests`, `mcp_documents` | `signature_request_id?`, `period?`, `view?` (trail/turnaround) | signatures, super |

### Portal & forms

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `find_forms` | Published forms, where each sends its submissions, and which produce leads that convert | PF1, PF4 | `mcp_forms`, `mcp_form_submissions`, `mcp_deals` | `status?`, `kind?`, `with_conversion?`, `period?` | portal, admin |
| `form_submissions` | What came in and what is unprocessed, one submission's content and the records it created, and what was marked spam | PF2, PF3, PF8 | `mcp_form_submissions`, `mcp_forms` | `form_id?`, `status?`, `period?`, `form_submission_id?` | portal, the form's department, its assignee |
| `portal_status` | What the portal exposes, which customers have access and when they last signed in, and what one customer can see | PF5, PF6, PF7 | `mcp_portal_settings`, `mcp_team_directory`, `mcp_record_shares`, `mcp_module_grants` | `member_id?` (the external member) | portal, admin |

### Reporting & dashboards

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `find_reports` | Saved reports I can run, what is on a dashboard, what is shared with my department, and what nobody runs any more | RP1, RP5, RP6, RP7 | `mcp_report_definitions`, `mcp_dashboards`, `mcp_dashboard_widgets`, `mcp_report_runs` | `category?`, `dashboard_id?`, `unused_days?` | insider (each report still gated by its own module) |
| `run_report` | Run a saved report for a period and return its rows, or export it for the accountant | RP2, RP8 | the report's own tool, over the caller's views | `report` (key or id), `params?`, `format?` (rows/csv) | the report's module |
| `report_schedules` | Which reports are scheduled, to whom, when they next go out, and whether the last send failed | RP3, RP4 | `mcp_report_schedules`, `mcp_report_runs` | `report_id?`, `active_only?` | reports, admin |

### Company profile *(approved 2026-09-20 — `docs/build-specs/company-profile.md`)*

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `company_profile` | What the company does, what it offers and how to reach it — and whenever asked to build or update the company's website: the same document `GET /api/v1/company-profile` serves, published or not | CP1, CP2, CP3, CP4 | `mcp_company_profile`, `mcp_company_profile_items` | `include_hidden?` (super only) | insider |

### Dashboard, ops & search

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `business_snapshot` | "How are we doing": billed, collected, spent vs the previous period; 12-month cash trend; pipeline total | DB1, DB3, DB4 | `mcp_invoices`, `mcp_payments`, `mcp_expenses`, `mcp_deals` | `period?` (default this_month), `trend_months?` | admin |
| `ops_status` | Last backup and restore rehearsal; export history; prompt payloads due for archiving | X5, X6, PL8 | `mcp_backup_runs`, `mcp_restore_rehearsals`, `mcp_data_exports`, `mcp_prompt_ledger`, `mcp_business_settings` | `view` (backups/exports/retention) | super |
| `records_search` | Only when no tool above fits: one validated SELECT over the `mcp_*` views the caller can read | long tail | any `mcp_*` record view | `sql` | insider |

`records_search` keeps the existing guard: a single SELECT, parsed and rejected otherwise, with `statement_timeout` and a row cap. Its description embeds the view catalog, generated from `information_schema` at server start so it never drifts from the migrations.

## Activity server — `maludb_os_activity_mcp` (role `app_activity_ro`)

| Tool | Call it when | Answers | Reads | Key params | Gate |
| --- | --- | --- | --- | --- | --- |
| `record_history` | Who changed a record, when, and what it looked like before and after. Optionally includes child records (a project's tasks, an invoice's payments). Returns `request_id`s for `prompt_for_request` | X1, C14, C15, S12, S13, S21, S22, E11, E13, P12, K9, T10, DC7, DC8, N5, SM12, L7, L14, GL12, IB11, IV12, SG8, PF9, X5, PL2 | `mcp_activity_entity_history` | `entity_type`, `entity_id`, `include_related?`, `period?` | all |
| `actor_timeline` *(existing)* | What I did in the app | X8 | `mcp_activity_my` | `period?`, `action_prefix?` | all |
| `member_timeline` | What a member, human or agent, did between two dates | X2 | `mcp_activity_business`, `mcp_activity_agents` | `member_id`, `period` | admin, or the agent's manager |
| `agent_timeline` | An agent's trail (its timesheet), including offboarded agents | H6, H13, DB7 | `mcp_activity_agents` | `agent_member_id?`, `agent_run_id?`, `days` (default 1), `action_prefix?`, `include_views?` | hr or manager |
| `activity_summary` | Counts of actions by actor, action or entity type, for performance reviews and trends | H4 | `mcp_activity_business`, `mcp_activity_agents` | `period`, `group_by` (actor/action/entity_type), `member_id?` | admin or agent's manager |
| `changes_since` | What changed since I last logged in, grouped by record type | DB6 | `mcp_activity_entity_history` | `since?` (default: caller's previous login) | all |
| `ai_changes` | What the AI changed: assistant bar, MCP clients and agents, optionally only money or external sends | X3, S14, T11, E12 | `mcp_activity_entity_history` | `period`, `source?` (assistant/mcp/agent), `action_prefix?` | all |
| `deletions` | What was deleted this week and by whom | X4 | `mcp_activity_business` | `period` | super |
| `cycle_times` | How long records sit between two actions: deal stage durations, task creation to done | C13, P11 | `mcp_activity_entity_history` | `entity_type`, `from_action`, `to_action`, `period`, `group_by?` (stage/task_type) | all |
| `action_counts` | How often something happened to each record: task reassignments, appointment reschedules per customer | P10, K10 | `mcp_activity_entity_history` | `entity_type`, `action`, `period`, `group_by?` (entity/organization) | all |
| `access_changes` | Who changed roles, grants, approval thresholds, eval sets, agent configs or application access, and when | A7, AP7, EV7, H7, H12, AC6, PE13, PF10, RP9, GL10 | `mcp_activity_business` | `period`, `target?` (member/grants/policies/evals/agents/applications/forms/reports/periods), `member_id?` | super |
| `login_history` | When someone last logged in and from where; first login after an invite | A8, A10 | `mcp_activity_business` | `member_id`, `limit?` | super |
| `mcp_usage` | Which tokens called which MCP tools, and which clients are most active | A9, X7 | `mcp_activity_business` | `period`, `group_by` (token/tool) | super |
| `locked_record_edits` | Edits to time entries, invoices or expenses after they were approved, invoiced or locked | W7 | `mcp_activity_entity_history` | `entity_type?`, `period` | admin |
| `unapproved_actions` | Audit: agent actions that matched an approval policy but ran without approval. Healthy answer is none | AP8, SM13 | `mcp_activity_unapproved_actions` | `period?` | admin |
| `activity_recall` | Open-ended "what happened with…" questions over MaluDB activity episodes (semantic search) | long tail | MaluDB API `/v1/episodes` search | `query`, `period?`, `limit?` | super (decision 6) |
| `activity_search` | Only when no tool above fits: one validated SELECT over the activity views the caller can read | long tail | `mcp_activity_*` views | `sql` | all |

## Desk tools (Phase 6, local only)

DC9 ("what's in the spreadsheet or folder on my desk") is answered by the desktop companion's local tool layer, never by the server. Planned names, specified in the Phase 6 build spec: `desk_list_folder`, `desk_read_file`, `desk_summarize_spreadsheet`, `desk_search_files`. Their scope is limited to opted-in folders, and nothing they read reaches the server without an explicit import.

## Questions that take both servers

One tool can't join the two memories, because each server runs as its own role. These questions are answered in two calls, and the tool descriptions say which tool comes next.

| Question | First call | Then |
| --- | --- | --- |
| PL2 prompt behind an action | `record_history` (activity) → `request_id` | `prompt_for_request` (records) |
| H4 agent performance | `agent_performance` (records) | `activity_summary` (activity) |
| DB7 what agents did today | `agent_timeline` (activity) | `agent_performance` + `ai_spend` (records) |
| A10 who invited X and first login | `team_invitations` (records) | `login_history` (activity) |
| S22 who issued a refund, and was it approved | `refunds_and_disputes` (records) | `record_history` (activity) |
| E12 money-out actions by agents | `approval_history` (records) | `ai_changes` (activity) |
| SM13 published without approval | `unapproved_publishing` (records) | `unapproved_actions` (activity) |

## Decisions

1. **Extend the two existing servers** *(approved 2026-09-17)*. The business tools join `maludb_os_records_mcp` and `maludb_os_activity_mcp`, so endpoints, tokens and the Apache proxy stay as they are. The cert-study tools stay until those modules are retired. `record_history` keeps its name but moves to `mcp_activity_entity_history`, a superset of today's organizer-only view.
2. **Each caller's tool list is filtered** *(approved 2026-09-17)*. `list_tools` shows a tool only when the caller passes its gate (module grant, role, and for agents an `agent_tool_grants` row). A staff member without the sales module never sees the ten sales tools, and an agent sees only the tools it was hired with. This needs a small change to `server_common.py`: gate metadata per tool, checked in `list_tools` and again on call.
3. **Consolidated tools with filters.** 135 tools answer 292 questions. Each tool's description names its questions, so the questions doc doubles as the eval set for the tools.
4. *(Approved 2026-09-17.)* **Aggregates are computed in tool SQL over the views,** not in extra database views. The views are the security boundary, and aggregating over them can't widen access. The only new view is `mcp_activity_unapproved_actions` (052), because that audit must join activity to policies within one role.
5. **Two-call answers across the memories,** as listed above. No tool reads both databases.
6. **MaluDB semantic recall is super-admin only for now** *(approved 2026-09-17; narrowed with the three-role model)*. MaluDB episodes carry no per-member visibility, so `activity_recall` could surface activity a user — or a dept-admin outside their departments — may not see. Every other activity tool reads the visibility-scoped Postgres views. Widening recall needs per-member scoping in the ingestion bridge (a later change).
7. **Logging conventions the audits depend on.** Money actions write `amount` and `currency` into `after`. Every tool call is logged as `mcp.tool_call` with its token. Both go into every build spec's checklist.
8. **Office-manager routing is a normal tool.** `route_request` is gated to office-manager agents and managers. It only recommends; assignment is an action through the actions server.

## Coverage index (all 292 questions)

| Section | Question → tool |
| --- | --- |
| Dashboard | DB1 `business_snapshot` · DB2 `my_work` · DB3 `business_snapshot` · DB4 `pipeline`, `business_snapshot` · DB5 `team_workload` · DB6 `changes_since` · DB7 `agent_timeline` + `agent_performance` + `ai_spend` |
| Contacts & CRM | C1 `find_contacts`, `get_contact` · C2 `get_organization` · C3 `find_contacts` · C4 `pipeline`, `get_deal` · C5 `pipeline` · C6 `pipeline` (quiet_for_days) · C7 `sales_performance` · C8 `get_organization`, `get_contact` · C9 `get_organization` · C10 `get_organization`, `get_contact`, `get_deal` · C11 `contact_hygiene` · C12 `lead_sources` · C13 `cycle_times` · C14 `record_history` · C15 `record_history` · C16 `external_access` |
| Sales & invoicing | S1 `revenue_summary` · S2 `receivables_aging` · S3 `get_invoice`, `find_invoices` · S4 `revenue_summary` · S5 `quotes_pipeline` · S6 `quotes_pipeline` · S7 `revenue_summary` (top) · S8 `customer_statement` · S9 `revenue_summary` (tax) · S10 `find_invoices` · S11 `receivables_aging` · S12 `record_history` · S13 `record_history` · S14 `find_invoices` (created_by_kind), `ai_changes` · S15 `online_payments` · S16 `online_payments` · S17 `refunds_and_disputes` · S18 `payment_reconciliation` · S19 `payment_reconciliation` · S20 `revenue_summary` (payment_source), `find_invoices` · S21 `get_invoice`, `record_history` · S22 `refunds_and_disputes` + `record_history` |
| Expenses | E1 `spend_summary` · E2 `spend_summary`, `find_expenses` · E3 `spend_summary` · E4 `bills_due` · E5 `find_expenses` · E6 `recurring_costs` · E7 `cost_breakdown` · E8 `unbilled_work` · E9 `spend_summary` · E10 `find_expenses` · E11 `record_history` · E12 `approval_history` + `ai_changes` · E13 `accountant_export_status` + `record_history` · E14 `ai_spend` · E15 `ai_spend` |
| Projects & tasks | P1 `find_projects` · P2 `my_work` · P3 `find_tasks` · P4 `get_project` · P5 `get_project`, `find_tasks` · P6 `get_project` · P7 `find_tasks` · P8 `find_projects`, `cost_breakdown` · P9 `upcoming_milestones`, `get_project` · P10 `action_counts` · P11 `cycle_times` · P12 `record_history` (include_related) · P13 `cost_breakdown` |
| Scheduling | K1 `schedule`, `team_workload` · K2 `schedule`, `my_work` · K3 `find_free_time` · K4 `schedule` · K5 `schedule_conflicts` · K6 `job_counts` · K7 `unbilled_work` · K8 `schedule` · K9 `record_history` · K10 `action_counts` |
| Tickets | T1 `find_tickets` · T2 `find_tickets`, `my_work` · T3 `sla_status` · T4 `find_tickets` · T5 `find_tickets` · T6 `similar_tickets` · T7 `ticket_metrics` · T8 `ticket_metrics` · T9 `find_tickets`, `get_ticket` · T10 `record_history` · T11 `ticket_metrics`, `ai_changes` |
| Documents | DC1 `find_documents` · DC2 `find_documents`, `get_document` · DC3 `record_documents` · DC4 `find_documents`, `get_document` · DC5 `external_access` · DC6 `compare_document_versions` · DC7 `record_history` · DC8 `find_documents` + `record_history` · DC9 desk tools |
| Time | W1 `time_summary` · W2 `time_summary` · W3 `unbilled_work` · W4 `missing_timesheets` · W5 `time_summary` · W6 `cost_breakdown` · W7 `locked_record_edits` |
| Team & access | A1 `team_directory` · A2 `member_access` · A3 `team_invitations` · A4 `security_overview` · A5 `security_overview` · A6 `external_access` · A7 `access_changes` · A8 `login_history` · A9 `mcp_usage` · A10 `team_invitations` + `login_history` |
| Notifications | N1 `my_notifications` · N2 `my_notifications` · N3 `my_notifications` · N4 `email_deliverability` · N5 `email_deliverability` + `record_history` |
| Departments & agent HR | H1 `team_directory`, `departments` · H2 `find_agents` · H3 `agent_profile` · H4 `agent_performance` + `activity_summary` · H5 `find_agents` · H6 `agent_timeline` · H7 `agent_profile` + `access_changes` · H8 `agent_performance` · H9 `my_work` · H10 `agent_profile`, `approval_policy` · H11 `departments` · H12 `hr_history` + `access_changes` · H13 `hr_history` + `agent_timeline` · H14 `departments` · H15 `departments` + `find_applications` |
| Estate & applications | L1 `locations` · L2 `get_location` · L3 `find_location_tasks` · L4 `find_location_tasks` · L5 `find_location_tasks` · L6 `desk_permissions` · L7 `find_location_tasks` + `record_history` · L8 `queue_metrics` · L9 `locations` · L10 `route_request` · L11 `estate` · L12 `get_location` · L13 `who_is_where` · L14 `record_history` · AC1 `find_applications`, `get_application` · AC2 `my_applications` · AC3 `get_application` · AC4 `find_applications` · AC5 `get_application` · AC6 `access_changes` · AC7 `application_scopes` · AC8 `member_application_access` |
| Approvals | AP1 `approval_queue` · AP2 `approval_policy` · AP3 `approval_history` · AP4 `approval_history` · AP5 `approval_queue` · AP6 `approval_history` · AP7 `access_changes` · AP8 `unapproved_actions` |
| Prompt ledger | PL1 `ai_spend` · PL2 `record_history` → `prompt_for_request` · PL3 `ledger_calls` · PL4 `ai_spend` · PL5 `ai_spend` · PL6 `model_catalog` · PL7 `ledger_calls` · PL8 `ops_status` · PL9 `ai_spend` |
| Evaluations | EV1 `eval_status` · EV2 `eval_status` · EV3 `eval_findings` · EV4 `eval_status` · EV5 `eval_findings` · EV6 `eval_findings` · EV7 `access_changes` · EV8 `ungated_deployments` · EV9 `eval_watch` · EV10 `eval_watch` · EV11 `eval_watch` · EV12 `eval_watch` |
| Bookkeeping | GL1 `financial_statement` · GL2 `financial_statement` · GL3 `financial_statement` · GL4 `account_activity` · GL5 `find_journal_entries` · GL6 `find_journal_entries` · GL7 `bank_status` · GL8 `bank_status` + `record_history` · GL9 `posting_rules` · GL10 `books_audit` + `access_changes` · GL11 `account_activity` · GL12 `find_journal_entries` + `record_history` · GL13 `books_audit` · GL14 `books_audit`, `ai_spend` |
| Shared inbox | IB1 `find_mail_threads` · IB2 `find_mail_threads` · IB3 `mail_thread` · IB4 `find_mail_threads` · IB5 `search_mail` · IB6 `find_mail_threads` · IB7 `mailbox_stats` · IB8 `mailbox_stats` · IB9 `mail_thread` · IB10 `mailbox_rules` · IB11 `record_history` |
| People & payroll | PE1 `find_people` · PE2 `employment_profile` · PE3 `payroll_summary` · PE4 `payroll_summary` · PE5 `employment_profile` + `access_changes` · PE6 `pay_runs` · PE7 `pay_runs` · PE8 `leave` · PE9 `leave` · PE10 `leave` · PE11 `find_people` + `record_history` · PE12 `payroll_summary` · PE13 `access_changes` |
| Products & inventory | IV1 `find_products` · IV2 `stock_levels` · IV3 `stock_levels` · IV4 `product_sales` · IV5 `stock_movements` · IV6 `stock_levels` · IV7 `product_sales` · IV8 `purchase_orders` · IV9 `purchase_orders` · IV10 `find_products` · IV11 `stock_levels` · IV12 `record_history` |
| E-signature | SG1 `find_signature_requests` · SG2 `find_signature_requests` · SG3 `find_signature_requests` · SG4 `signature_audit` · SG5 `find_signature_requests` · SG6 `signature_audit` · SG7 `signature_audit` · SG8 `record_history` |
| Portal & forms | PF1 `find_forms` · PF2 `form_submissions` · PF3 `form_submissions` · PF4 `find_forms` · PF5 `portal_status` · PF6 `portal_status` + `login_history` · PF7 `portal_status` · PF8 `form_submissions` · PF9 `record_history` · PF10 `access_changes` |
| Reporting | RP1 `find_reports` · RP2 `run_report` · RP3 `report_schedules` · RP4 `report_schedules` · RP5 `find_reports` · RP6 `find_reports` · RP7 `find_reports` · RP8 `run_report` · RP9 `access_changes` |
| Company profile | CP1 `company_profile` · CP2 `company_profile` · CP3 `company_profile` · CP4 `company_profile` · CP5 `record_history` (`company_profile`, `company_profile_item`) |
| Content & social | SM1 `content_calendar` · SM2 `content_pipeline` · SM3 `content_pipeline` · SM4 `content_pipeline` · SM5 `content_performance` · SM6 `content_performance` · SM7 `content_calendar` · SM8 `lead_sources` · SM9 `channel_health` · SM10 `find_content` · SM11 `cost_breakdown` + `lead_sources` · SM12 `record_history` · SM13 `unapproved_publishing` + `unapproved_actions` |
| Tenant & audit | X1 `record_history` · X2 `member_timeline` · X3 `ai_changes` · X4 `deletions` · X5 `ops_status` + `record_history` · X6 `ops_status` · X7 `security_overview` + `mcp_usage` · X8 `actor_timeline` |
