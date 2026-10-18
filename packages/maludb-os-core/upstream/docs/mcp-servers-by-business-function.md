# MCP servers by business function

2026-09-20 · Reference, generated from the live tool registries (not from the design drafts).

> **What this is.** The Business OS exposes its data and its actions to AI agents and to people's own AI clients through four MCP servers (plus the assistant that drives them). This page orders every tool by the **business function** it serves — sales, service, finance, HR and so on — so you can answer "what can an agent do for Accounting?" without knowing which server a tool lives on. The per-tool design record (question ids, views read, gates) is `docs/business-os-mcp-tool-surface.md`; the write surface is `docs/business-os-action-manifest.md`.

> **Counted 2026-09-20 from the running code:** **125** records tools, **9** activity tools, **3** memory tools and **335** action tools (**472** in all). Of the action tools, 333 are manifest actions and two are navigation (`find_screen`, `navigate`).

## 1. The servers at a glance

| Server | Systemd unit | Port | Reads / writes | Who reaches it | What it is for |
| --- | --- | --- | --- | --- | --- |
| **Records** (`maludb_os_records_mcp`) | `maludb-os-records-mcp` | 8811 | Read-only, role `app_records_ro`, `mcp_*` views only | People and agents; public at `/mcp/records` | The business's record memory: every "what is / who is / how many" question about customers, money, work, people and estate. **125 tools.** |
| **Activity** (`maludb_os_activity_mcp`) | `maludb-os-activity-mcp` | 8812 | Read-only, role `app_activity_ro` | People and agents; public at `/mcp/activity` | Who did what and when: the audit trail behind every record. **9 tools.** |
| **Actions** (`maludb_os_actions_mcp`) | `maludb-os-actions-mcp` | 8813 | **Writes** — POSTs to the PHP handlers as the caller | The assistant and hired agents only; **not** on the public port | Everything that changes state, plus screen navigation. One tool per built manifest action. **335 tools.** |
| **Memory** (`maludb_os_memory_mcp`) | `maludb-os-memory-mcp` | 8814 | Read-only over MaluDB; holds the tenant token so no one else does | Agents and people; **not** on the public port | Shared memory (what we know, what was said before, standing facts). Writes are manifest actions, never here. **3 tools.** |
| **Assistant** (`maludb-os-assistant`) | `maludb-os-assistant` | 8765 | — | The command bar in the web app | Not an MCP server: the LLM router that consumes the Records, Activity and Actions tools on behalf of the person typing. |

Supporting services (not MCP): `maludb-os-agent-runner` (runner API 8815 and prompt-ledger proxy 8816) runs hired agents and hands each run a scoped token; `maludb-os-activity-ingest.timer` ships `activity_log` to MaluDB every minute.

### How every call is authorised

- **Authentication is a bearer token** on every request: a personal MCP token (`php bin/mint_mcp_token.php`), an action token (the Actions server accepts only these) or an agent run token. No token, or an unknown one, is a `401`.
- **Row visibility is decided in SQL, not in the tool.** Each read tool selects from `mcp_*` views that embed the caller's visibility rules, so a person and an agent asking the same question see only what that caller may see, and a hidden record looks the same as one that does not exist.
- **Agents are also gated per tool.** A person sees every tool on a server; a hired agent lists and may call only the tools it holds a live `agent_tool_grants` row for on that server (`mcp/agent_grants.py`, enforced at the MCP boundary). The four endpoints are registered as `Records MCP`, `Activity MCP`, `Actions MCP` and `Memory MCP`.
- **Writes go through PHP.** Action tools POST to the same handlers the React screens use, so the same `require_post` / CSRF / authorisation / `log_activity` rules apply and an approval policy can answer `pending_approval` instead of acting. Every create returns `record_id`.
- **Gate vocabulary** (used in the action manifest): `super` = super-admin only · `admin` = super-admin, or a dept-admin inside their own departments · `mod:x` = either of those, or a holder of module grant *x* · `own` = the caller's own records.
- **What is recorded:** every write is logged to `activity_log` by its PHP handler; an agent run's tool events land in `agent_run_events` and its model calls in the prompt ledger. Plain read calls are not separately logged by the servers.

## 2. Contents — by business function

1. [Front office & business overview](#3-front-office--business-overview) — 5 read tools · 18 actions
2. [Sales & customers](#4-sales--customers) — 18 read tools · 66 actions
3. [Customer service](#5-customer-service) — 10 read tools · 31 actions
4. [Marketing & content](#6-marketing--content) — 6 read tools · 20 actions
5. [Operations & delivery](#7-operations--delivery) — 15 read tools · 57 actions
6. [Finance & accounting](#8-finance--accounting) — 11 read tools · 35 actions
7. [People & HR](#9-people--hr) — 6 read tools · 27 actions
8. [AI workforce (Agent HR)](#10-ai-workforce-agent-hr) — 11 read tools · 26 actions
9. [Documents & agreements](#11-documents--agreements) — 6 read tools · 19 actions
10. [Governance, approvals & audit](#12-governance-approvals--audit) — 12 read tools · 19 actions
11. [IT, estate & applications](#13-it-estate--applications) — 7 read tools · 15 actions
12. [Cross-cutting tools](#14-cross-cutting-tools) — search, navigation
13. [Legacy: community & certification study](#15-legacy-community--certification-study) — 28 tools from the original app
14. [Coverage and known gaps](#16-coverage-and-known-gaps)

Each section lists **read tools** in a table (all read-only) and then the **action tools** that change that function's records. Reading tools are the place to start: an agent should read with one, then act with the Actions server.

## 3. Front office & business overview

What the owner and the front of the business look at first: what is waiting on me, who the company is, and the saved reports and dashboards that summarise every other function.

| Tool | Server | Call it when | Key params |
| --- | --- | --- | --- |
| `my_work` | Records | Everything waiting on the caller, across every module, in one answer: approvals to decide, open tickets (with SLA state), mail conversations assigned to them that wait on us… | `horizon_days?` |
| `company_profile` | Records | Who the company is, what it offers and how to reach it: name, tagline, about, mission, facts (founded, industry, headquarters, team size), contact details and address, social… | `include_hidden?` |
| `find_reports` | Records | Saved reports the caller can run — what each reads, how it is drawn, who owns it, whether it is shared, when it was last run and how often — or the tiles of one dashboard, or… | `category?`, `dashboard_id?`, `unused_days?` |
| `run_report` | Records | Run a saved report and return its rows (format='csv' for text an accountant can open). | `report`, `params?`, `format?` |
| `report_schedules` | Records | Which reports go out on a schedule, to whom (people of this business — a link is mailed, never the figures), when each next goes out and how the last delivery went. | `report_id?`, `active_only?` |

**Actions server — 18 tools** (writes; `†` = an approval policy may hold it for a person):

- `notification_mark_read`
- `report_save`, `report_run`, `report_export`, `report_archive`, `report_schedule_save`†, `report_schedule_pause`
- `dashboard_save`, `dashboard_widget_save`, `dashboard_widget_remove`
- `company_profile_update`, `company_profile_media_set`, `company_profile_media_remove`, `company_profile_item_create`, `company_profile_item_update`, `company_profile_item_move`, `company_profile_item_delete`, `company_profile_publish`†

## 4. Sales & customers

The customer record and the money that comes in: companies, people, deals and pipeline, quotes, invoices, receivables, and the public forms and portal customers use.

| Tool | Server | Call it when | Key params |
| --- | --- | --- | --- |
| `find_contacts` | Records | Look up any person or company by name, email, phone or fragment, or list customers, vendors, leads or partners. | `q?`, `kind?`, `relationship_type?`, `tag?`, `owner_member_id?`, `limit?` |
| `get_organization` | Records | Everything about one company: its people, its deals, its recent conversations and who owns the relationship. | `organization_id`, `interactions_limit?` |
| `get_contact` | Records | One person: how to reach them, which company they are at, the deals they are the main contact on, and the last conversations with them. | `contact_id`, `interactions_limit?` |
| `get_deal` | Records | One deal in full: stage, value, probability, expected close, owner, and the conversations attached to it. | `deal_id`, `interactions_limit?` |
| `pipeline` | Records | Where the open deals stand: what is in each stage, what is due to close, what has gone quiet, and the totals per stage, owner or month. | `stage?`, `owner_member_id?`, `closing_period?`, `quiet_for_days?`, `group_by?`, `limit?` |
| `sales_performance` | Records | Win rate, won and lost counts and average deal size over a period, by owner, source or the stage deals were in when they closed. | `period?`, `date_from?`, `date_to?`, `group_by?` |
| `contact_hygiene` | Records | Contacts nobody owns, and records that look like duplicates of each other (similar names or a shared email address). | `check?`, `similarity?`, `limit?` |
| `lead_sources` | Records | Where the business came from: deals and their value grouped by source, campaign or the piece of content that brought them in. | `period?`, `date_from?`, `date_to?`, `group_by?`, `won_only?` |
| `find_invoices` | Records | List invoices by status, customer, project, number or period, or just the overdue ones. | `status?`, `organization_id?`, `project_id?`, `number?`, `overdue?`, `period?`, … |
| `get_invoice` | Records | One invoice in full: its lines, the payments applied to it, any credit notes, and what is still owed. | `invoice_id?`, `number?` |
| `receivables_aging` | Records | Who owes us money and how overdue it is, in the usual buckets (not yet due, 1–30, 31–60, 61–90, 90+), per customer and per currency, plus how long customers take to pay on… | `organization_id?`, `as_of?` |
| `revenue_summary` | Records | What we invoiced, collected or charged in tax over a period, by month, customer or tax rate. | `metric?`, `period?`, `group_by?` |
| `customer_statement` | Records | One customer's account: every invoice, payment and credit in date order with a running balance. | `organization_id`, `period?` |
| `quotes_pipeline` | Records | Quotes still outstanding, quotes that have expired, and how many quotes turn into invoices. | `status?`, `period?`, `include_conversion?` |
| `unbilled_work` | Records | Billable work not yet on an invoice, per customer. | `organization_id?`, `kinds?` |
| `find_forms` | Records | The forms the business publishes: address (/f/<slug>), status, what a submission does (keep it, make a contact, open a ticket, start a deal), where it is routed (department… | `status?`, `kind?`, `with_conversion?`, `period?` |
| `form_submissions` | Records | What came in through the forms, newest first: status 'new' is what waits for someone; 'spam' is what the trap field or a person marked. | `form_id?`, `status?`, `period?`, `form_submission_id?` |
| `portal_status` | Records | The customer portal: whether it is on and which areas it shows (appointments and online payment are stored switches the portal cannot honour yet), and which customers have… | `member_id?` |

**Actions server — 66 tools** (writes; `†` = an approval policy may hold it for a person):

- `organization_create`, `organization_update`, `organization_archive`, `organization_merge`, `organization_delete`†
- `contact_create`, `contact_update`, `contact_set_primary`, `contact_archive`, `contact_merge`, `contact_delete`†
- `deal_create`, `deal_update`, `deal_move_stage`, `deal_mark_won`, `deal_mark_lost`, `deal_delete`†
- `interaction_log`, `interaction_update`, `interaction_delete`†
- `pipeline_save`, `pipeline_stage_save`
- `tag_add`, `tag_remove`
- `comment_add`, `comment_delete`†
- `quote_create`, `quote_update`, `quote_add_line`, `quote_remove_line`, `quote_send`†, `quote_accept`, `quote_decline`, `quote_convert`, `quote_delete`†
- `invoice_create`, `invoice_update`, `invoice_add_line`, `invoice_remove_line`, `invoice_add_unbilled`, `invoice_send`†, `invoice_send_reminder`†, `invoice_void`†, `invoice_write_off`†, `invoice_delete`†
- `payment_record`, `payment_allocate`, `payment_unallocate`, `payment_delete`†
- `credit_note_create`, `credit_note_issue`†
- `statement_send`†
- `catalog_item_save`, `catalog_item_archive`
- `tax_rate_save`, `tax_rate_archive`
- `form_save`, `form_field_save`, `form_field_remove`, `form_publish`, `form_close`, `form_submission_process`, `form_submission_mark_spam`, `form_submission_reject`
- `portal_settings_update`, `portal_access_invite`†

## 5. Customer service

Requests from customers after the sale: the helpdesk (tickets, SLAs) and the shared mailboxes mail arrives in.

| Tool | Server | Call it when | Key params |
| --- | --- | --- | --- |
| `find_tickets` | Records | Tickets, newest first, with their SLA due times. | `status?`, `department_id?`, `assignee_member_id?`, `priority?`, `organization_id?`, `unreplied?`, … |
| `get_ticket` | Records | One ticket with its whole thread — the request, every public reply and, for people who work here, the internal notes (a portal customer never receives those). | `ticket_id?`, `number?` |
| `sla_status` | Records | Tickets that have breached an SLA target, or will within the next N minutes (default 60): which target (first response or resolution), when it is due, how late it is. | `within_minutes?`, `department_id?` |
| `similar_tickets` | Records | "Have we seen this before, and how was it fixed?" — full-text search over ticket subjects, descriptions and threads, best match first, with each ticket's resolution summary. | `q`, `resolved_only?` |
| `ticket_metrics` | Records | Helpdesk numbers for tickets opened in a period, grouped by category, department, or who worked them (people vs agents): how many were opened and resolved, median hours to… | `period?`, `date_from?`, `date_to?`, `group_by?` |
| `find_mail_threads` | Records | Conversations in the shared inbox, newest first. | `mailbox_id?`, `status?`, `assigned_to_me?`, `unassigned?`, `unread_only?`, `unanswered?`, … |
| `mail_thread` | Records | One conversation in full — every message in order (who, when, the text), its attachments and whether each was filed in Documents — or, given organization_id, that customer's… | `mail_thread_id?`, `organization_id?` |
| `search_mail` | Records | Find the email where someone said something — full text over subject, sender and body, newest first, with the matching words in context. | `q`, `mailbox_id?`, `period?`, `direction?` |
| `mailbox_stats` | Records | How the inbox is doing for conversations started in a period, by mailbox or by the person who first answered: conversations received, how many were answered, the median hours… | `period?`, `date_from?`, `date_to?`, `group_by?` |
| `mailbox_rules` | Records | The mailboxes we receive mail on — address, department, whether it is on, when it was last checked and whether that failed, how many conversations are open — and the routing… | `mailbox_id?` |

**Actions server — 31 tools** (writes; `†` = an approval policy may hold it for a person):

- `ticket_create`, `ticket_update`, `ticket_assign`, `ticket_set_priority`, `ticket_set_status`, `ticket_reply`†, `ticket_add_note`, `ticket_resolve`, `ticket_reopen`, `ticket_close`, `ticket_delete`†, `ticket_category_save`
- `business_hours_save`
- `sla_policy_update`
- `portal_request_create`, `portal_request_reply`
- `mail_send`†, `mail_reply`†, `mail_draft_save`, `mail_thread_assign`, `mail_thread_set_status`, `mail_thread_link`, `mail_thread_to_ticket`, `mail_thread_mark_read`, `mail_thread_star`, `mail_attachment_file`, `mail_rule_save`, `mail_rule_delete`†
- `mailbox_save`, `mailbox_sync_now`, `mailbox_disable`

## 6. Marketing & content

What the business publishes and how it performed: the content calendar and pipeline, channels, and campaign results.

| Tool | Server | Call it when | Key params |
| --- | --- | --- | --- |
| `content_calendar` | Records | What is going out when, per channel: variants planned (scheduled) or already published in a period, in time order — and, with gaps_within_days, the channels with nothing… | `period?`, `date_from?`, `date_to?`, `channel_id?`, `gaps_within_days?` |
| `content_pipeline` | Records | Content on its way out and who it waits on: drafts, items in review (waiting on their reviewer), approved items not yet scheduled, agent-drafted items, and failed publishes. | `status?`, `author_kind?`, `failed_only?` |
| `content_performance` | Records | How published posts did, best first by a chosen metric (default engagements), using each post's LATEST recorded numbers — for one campaign, one channel, a period, or all. | `campaign_id?`, `period?`, `channel_id?`, `top?`, `metric?` |
| `channel_health` | Records | The channels we publish on and the state of each connection: connected, not connected, expired or in error, with the last error. | — |
| `find_content` | Records | "Have we already posted about this, and when?" — full-text search over content titles, briefs and the words written for each channel, best match first, with where and when… | `q`, `published_only?` |
| `unapproved_publishing` | Records | Audit: content published without the approval it needed. | `period?` |

**Actions server — 20 tools** (writes; `†` = an approval policy may hold it for a person):

- `campaign_create`, `campaign_update`, `campaign_set_status`, `campaign_delete`†
- `content_create`, `content_update`, `content_write_variant`, `content_attach_media`, `content_submit_for_review`, `content_approve`, `content_request_changes`, `content_schedule`†, `content_unschedule`, `content_publish`†, `content_mark_published`, `content_record_metrics`, `content_archive`, `content_delete`†
- `channel_save`, `channel_archive`

## 7. Operations & delivery

Getting the work done: projects and tasks, scheduling and free time, time tracking, and products, stock and purchase orders.

| Tool | Server | Call it when | Key params |
| --- | --- | --- | --- |
| `find_projects` | Records | Projects and how they are going: which are active, who they are for, how far along, and (with over_budget) which have run past the hours or money they were given. | `q?`, `status?`, `organization_id?`, `department_id?`, `over_budget?`, `include_archived?`, … |
| `get_project` | Records | One project in full: who is on it and what each of them is doing, how far along it is, what is blocking it, and its milestones. | `project_id`, `tasks_limit?` |
| `find_tasks` | Records | Tasks by who they are on, which project, and what state they are in — including what is overdue, what is blocked and what agents are working on. | `q?`, `assignee_member_id?`, `assignee_kind?`, `project_id?`, `department_id?`, `status?`, … |
| `upcoming_milestones` | Records | Milestones falling due across the projects you can see — 'what is coming up in the next two weeks'. | `within_days?`, `project_id?`, `include_completed?` |
| `schedule` | Records | What is on the calendar in a window (default the coming week): each occurrence with its time, title, customer, place, crew and resources. | `date_from?`, `date_to?`, `member_id?`, `resource_id?`, `include_cancelled?` |
| `find_free_time` | Records | Who is free for a job of duration_minutes between two moments (default the next three days), optionally within one department: for each person, their first free slots and how… | `duration_minutes?`, `date_from?`, `date_to?`, `department_id?`, `member_ids?` |
| `schedule_conflicts` | Records | Double bookings in a window (default the coming week): pairs of overlapping busy intervals for the same person or the same resource — two appointments, or an appointment… | `date_from?`, `date_to?`, `member_id?`, `resource_id?` |
| `job_counts` | Records | How many appointments / jobs in a period, by type, person, customer or status, with hours booked. | `date_from?`, `date_to?`, `group_by?` |
| `time_summary` | Records | Where the hours went: total and billable hours, utilization (billable ÷ total, %) and the number of entries, grouped by project, customer, person or day. | `period?`, `date_from?`, `date_to?`, `group_by?`, `member_id?`, `project_id?` |
| `missing_timesheets` | Records | Who has logged no time in a period (default this week) — people only, never agents. | `period?`, `department_id?` |
| `find_products` | Records | What we sell: SKU, name, kind, price, how many are on hand, the reorder point, the usual supplier — and the average cost, for someone with the inventory grant. | `q?`, `kind?`, `supplier_organization_id?`, `include_archived?` |
| `stock_levels` | Records | How much we have and where: quantity per product per location, what is at or below its reorder point, what has gone negative, when it was last counted — and, with… | `product_id?`, `stock_location_id?`, `below_reorder_only?`, `negative_only?`, `valuation?` |
| `stock_movements` | Records | What moved in or out, when, at what unit cost, and against which document (an invoice, a purchase order) — newest first, signed quantities. | `product_id?`, `stock_location_id?`, `kind?`, `period?`, `date_from?`, `date_to?` |
| `product_sales` | Records | What sold in a period, by product or by customer: units and revenue from invoices that were sent (not drafts, not void), and — with the inventory grant — the cost of what… | `period?`, `date_from?`, `date_to?`, `product_id?`, `group_by?` |
| `purchase_orders` | Records | Purchase orders: supplier, status, expected date, whether it is late, the total, the bill it became — and with outstanding_only=true, each line still to arrive. | `status?`, `vendor_organization_id?`, `period?`, `outstanding_only?` |

**Actions server — 57 tools** (writes; `†` = an approval policy may hold it for a person):

- `project_create`, `project_update`, `project_set_status`, `project_add_member`, `project_remove_member`, `project_archive`, `project_delete`†
- `milestone_save`, `milestone_complete`, `milestone_delete`†
- `task_create`, `task_update`, `task_assign`, `task_set_status`, `task_complete`, `task_reopen`, `task_reschedule`, `task_add_dependency`, `task_remove_dependency`, `task_delete`†
- `checklist_item_add`, `checklist_item_toggle`
- `appointment_create`, `appointment_update`, `appointment_reschedule`, `appointment_assign`, `appointment_unassign`, `appointment_respond`, `appointment_book_resource`, `appointment_release_resource`, `appointment_complete`, `appointment_cancel`, `appointment_delete`†, `appointment_type_save`
- `availability_block_create`, `availability_block_delete`†
- `bookable_resource_save`
- `time_log`, `time_update`, `time_delete`†
- `timer_start`, `timer_stop`
- `timesheet_submit`, `timesheet_approve`, `timesheet_reject`
- `product_save`, `product_archive`
- `stock_location_save`, `stock_adjust`, `stock_transfer`, `stock_count_record`, `stock_write_off`†
- `purchase_order_save`, `purchase_order_send`†, `purchase_order_receive`, `purchase_order_to_bill`†, `purchase_order_cancel`

## 8. Finance & accounting

Money going out and the books: expenses and bills, the double-entry ledger, statements, bank reconciliation and the accountant export.

| Tool | Server | Call it when | Key params |
| --- | --- | --- | --- |
| `spend_summary` | Records | Spend over a period by category, vendor or month, or how much went on a particular thing (use q for a fragment of the description or vendor). | `period?`, `group_by?`, `q?`, `category_id?`, `vendor_organization_id?`, `compare_to_average_months?` |
| `find_expenses` | Records | List expenses: missing a receipt, matching some text, or submitted_by_me for "what did I submit and what's its status". | `q?`, `period?`, `status?`, `missing_receipt?`, `submitted_by_me?`, `limit?` |
| `bills_due` | Records | Unpaid or scheduled bills (expenses with a due date) due within N days, most urgent first, with a per-currency total. | `within_days?` |
| `recurring_costs` | Records | Subscriptions, rent and other recurring costs, each with its monthly-equivalent amount (weekly x52/12, monthly x1, quarterly /3, yearly /12, rounded to 2dp) so different… | `active_only?` |
| `accountant_export_status` | Records | What went into the accountant export for a period — its format, row counts and when it was last downloaded. | `period?` |
| `financial_statement` | Records | Profit and loss, balance sheet or trial balance for a fiscal period. | `statement`, `period?`, `compare_to?`, `department_id?` |
| `account_activity` | Records | One account's opening balance, the period's movements and its closing balance — for a receivable or payable account, what we were owed or owed at period end (GL11). | `account`, `period?`, `organization_id?` |
| `find_journal_entries` | Records | Journal entries by period, status or source, or what a specific document posted — pair source_entity_type and source_entity_id to answer 'what did INV-00003 post' (GL6). | `period?`, `status?`, `source?`, `source_entity_type?`, `source_entity_id?`, `limit?` |
| `bank_status` | Records | Each bank account's reconciliation state and the gap to its last statement, plus unmatched bank transactions. | `bank_account_id?`, `period?`, `unmatched_only?` |
| `posting_rules` | Records | Which document type or expense category posts to which accounts — the rules are read, never hard-coded, so this is the authoritative answer to 'what account does an… | `source?` |
| `books_audit` | Records | The bookkeeping audit set: period close/reopen history (`check=periods`), reversals of posted entries (`check=edits`), and the other integrity checks. | `check?`, `period?` |

**Actions server — 35 tools** (writes; `†` = an approval policy may hold it for a person):

- `expense_create`, `expense_update`, `expense_submit`, `expense_approve`, `expense_reject`, `expense_mark_paid`†, `expense_mark_reimbursed`†, `expense_attach_receipt`, `expense_delete`†, `expense_category_save`, `expense_category_archive`
- `recurring_expense_create`†, `recurring_expense_update`, `recurring_expense_pause`, `recurring_expense_delete`†
- `accountant_export_create`
- `gl_account_save`, `gl_account_archive`
- `journal_entry_save`, `journal_entry_post`†, `journal_entry_reverse`†, `journal_entry_void`
- `books_post_documents`†
- `fiscal_period_save`, `fiscal_period_close`, `fiscal_period_reopen`
- `posting_rule_save`
- `bank_account_save`, `bank_import_statement`, `bank_transaction_match`, `bank_transaction_unmatch`, `bank_transaction_ignore`, `bank_transaction_to_expense`†
- `reconciliation_start`, `reconciliation_complete`

## 9. People & HR

The human side of HR: employment records, pay runs and leave, plus the team directory, invitations and access.

| Tool | Server | Call it when | Key params |
| --- | --- | --- | --- |
| `find_people` | Records | Employees, contractors and interns the caller may see — job title, department, manager, where they work, status, start and end dates. | `status?`, `department_id?`, `employment_type?`, `starting_or_leaving?` |
| `employment_profile` | Records | One person's employment details AND pay — type, rate, currency, schedule, weekly hours — with the history of every pay change. | `member_id?` |
| `payroll_summary` | Records | What people cost in a period, from PAID pay runs, by department, person or month: gross, deductions, net, employer costs, and — beside it — the hours those people logged and… | `period?`, `date_from?`, `date_to?`, `group_by?`, `member_id?` |
| `pay_runs` | Records | Pay runs and, for one run, each person's lines and the journal entry it posted. HR and super-admin only. | `pay_run_id?`, `status?`, `period?` |
| `leave` | Records | Leave balances (`my_balance`), requests waiting for a decision (`pending`), and who is off in a date range (`calendar`). | `view?`, `period?`, `date_from?`, `date_to?`, `member_id?` |
| `team_invitations` | Records | Who has been invited and has not yet accepted: the address, what they will be (user, dept_admin or super_admin), who invited them, when, and whether the link has expired. | — |

**Actions server — 27 tools** (writes; `†` = an approval policy may hold it for a person):

- `invitation_send`†, `invitation_resend`†, `invitation_revoke`
- `member_set_role`
- `module_grant_set`, `module_grant_revoke`
- `department_save`, `department_add_member`, `department_remove_member`
- `profile_update`
- `business_settings_update`
- `mcp_token_create`, `mcp_token_revoke`
- `employment_profile_save`, `employment_end`
- `compensation_change_save`†
- `pay_run_create`, `pay_run_item_save`, `pay_run_remove_person`, `pay_run_approve`†, `pay_run_mark_paid`†, `pay_run_void`
- `leave_request_create`, `leave_request_decide`, `leave_request_cancel`, `leave_balance_adjust`, `leave_type_save`

## 10. AI workforce (Agent HR)

Hiring and managing agents like staff: who they are, what they may do, what they did, and what they know. Includes the shared Memory server and the skills catalogue.

| Tool | Server | Call it when | Key params |
| --- | --- | --- | --- |
| `find_agents` | Records | Which agents we employ, what each does, who manages them, their model and monthly budget. | `department_id?`, `status?`, `kind?` |
| `agent_profile` | Records | One agent's job description, model, tool grants, schedule and config history — what it may do, and what it needs a human for. | `agent_member_id?` |
| `hr_history` | Records | Hire, suspend, reinstate, offboard and other HR events for a person or an agent — the employment record. | `member_id`, `include_reviews?` |
| `agent_runs` | Records | What an agent is doing or did: its runs with what each was asked, what it answered, its status, trigger and cost. | `agent_member_id?`, `status?`, `days?`, `parent_run_id?`, `limit?` |
| `agent_performance` | Records | How agents perform over a period: runs (succeeded, failed, waiting for approval), tasks closed, tickets resolved, escalations and what they were about, spend this month… | `agent_member_id?`, `days?` |
| `ledger_calls` | Records | Individual model calls from the prompt ledger: failures, timeouts, rate limits and budget refusals; every call a run made, with tokens, latency and cost. | `agent_run_id?`, `agent_member_id?`, `status?`, `days?`, `limit?` |
| `prompt_for_request` | Records | The full prompt and response behind an action: every model call that shares a request_id, in order, with the exact context sent (system prompt, messages, tool definitions)… | `request_id`, `include_payloads?` |
| `skill_catalog` | Records | Which skills exist in the business, who has them, and what agents have written that is waiting for review. | `agent_member_id?`, `skill_name?`, `proposals?` |
| `recall` | Memory | What do we know about X? Searches the memory you may read — your own, your departments' and the organisation's — and says where each result came from. | `query`, `subject?`, `scope?`, `limit?` |
| `core_memory` | Memory | The small set of standing facts and preferences kept for one agent or person — what is in force all the time, as opposed to what recall finds on demand. | `member_id?` |
| `session_search` | Memory | What was said in earlier runs and chats. Finds messages containing the words, with the run they came from. | `query`, `agent_member_id?`, `limit?` |

**Actions server — 26 tools** (writes; `†` = an approval policy may hold it for a person):

- `agent_hire`, `agent_update_config`, `agent_activate_version`, `agent_set_manager`, `agent_set_kind`, `agent_add_subagent`, `agent_remove_subagent`, `agent_run_duty_now`, `agent_run_start`†, `agent_run_cancel`, `agent_delegate`, `agent_suspend`, `agent_reinstate`, `agent_offboard`
- `escalation_raise`, `escalation_resolve`
- `performance_review_create`
- `system_prompt_save`, `system_prompt_version_create`, `system_prompt_archive`
- `memory_remember`†
- `core_memory_set`
- `skill_propose`†, `skill_proposal_decide`†, `skill_assign`†, `skill_unassign`†

## 11. Documents & agreements

The written record: files, procedures and handbooks with version history, and e-signature requests with their evidence.

| Tool | Server | Call it when | Key params |
| --- | --- | --- | --- |
| `find_documents` | Records | Find a file, procedure, handbook or page by name or by what it says. | `q?`, `kind?`, `department_id?`, `folder_id?`, `origin?`, `limit?` |
| `get_document` | Records | Read one document: a page's / procedure's / handbook's full Markdown body, or a file's facts (its bytes are downloaded from the Documents screen, never returned here), with… | `document_id` |
| `record_documents` | Records | Documents attached to a customer, contact, deal, project, task, invoice, quote, expense, ticket or content item. | `entity_type`, `entity_id` |
| `compare_document_versions` | Records | What changed between two versions of a written page, procedure or handbook: a unified line diff, plus each version's note and date. | `document_id`, `from_version`, `to_version` |
| `find_signature_requests` | Records | What is out for signature: each request with its document, who has signed and who we are still waiting on, when it was sent and when its links expire. | `status?`, `entity_type?`, `entity_id?`, `organization_id?`, `expiring_within_days?` |
| `signature_audit` | Records | The evidence behind a signature: the step-by-step trail with the signed-content fingerprint (`trail`), or turnaround times over a period (`turnaround`). | `signature_request_id?`, `view?`, `period?`, `date_from?`, `date_to?` |

**Actions server — 19 tools** (writes; `†` = an approval policy may hold it for a person):

- `document_upload`, `document_update`, `document_move`, `document_restore_version`, `document_link`, `document_unlink`, `document_archive`, `document_delete`†
- `page_create`
- `folder_save`, `folder_delete`†
- `signature_request_create`, `signature_request_send`†, `signature_signer_save`, `signature_signer_remove`, `signature_request_remind`†, `signature_request_void`, `signature_document_file`, `signature_provider_save`

## 12. Governance, approvals & audit

Who approved what, what the AI cost, whether it was evaluated, and the trail of everything done in the system. The Audit and Accounting departments live here.

| Tool | Server | Call it when | Key params |
| --- | --- | --- | --- |
| `approval_queue` | Records | What is waiting for my approval, and the status of requests I made. | `role?`, `status?`, `limit?` |
| `approval_policy` | Records | Which actions need a person's approval, for whom, above what amount, and who approves. | `agent_member_id?`, `department_id?`, `action_key?`, `include_inactive?` |
| `approval_history` | Records | What was approved, rejected, withdrawn or left to expire, by whom and how long each decision took (decision_minutes). | `period?`, `date_from?`, `date_to?`, `status?`, `decided_by?`, `category?`, … |
| `ai_spend` | Records | What the models cost: calls, failures, tokens, average latency, cost and what prompt caching saved — grouped by agent, model, provider, location, project, department or day… | `period?`, `date_from?`, `date_to?`, `group_by?`, `agent_member_id?`, `view?` |
| `model_catalog` | Records | Which models are registered, the harness each runs on, its context window and its prices per million tokens (input, output, cache read, cache write). | `status?` |
| `eval_status` | Records | Eval runs and their scores: did a candidate pass its hiring evals, an agent's score over time, whether the last change regressed against its baseline. | `agent_member_id?`, `eval_set_id?`, `trigger?`, `compare_to_baseline?` |
| `eval_findings` | Records | What the evals found: the cases that fail most (failing_cases), the cases made from real traces and where each came from (promoted), or production runs that graded poorly… | `view?`, `period?`, `agent_member_id?` |
| `eval_watch` | Records | The Audit department's standing watch: which eval sets are on a schedule and when each runs next, and the degradation alerts that are open — threshold breaches, regressions… | `agent_member_id?`, `status?`, `severity?` |
| `ungated_deployments` | Records | Audit: agent configuration versions that went live WITHOUT a passing eval run behind them. | `period?` |
| `actor_timeline` | Activity | The caller's own activity trail (what they did in the app, when). | `date_from?`, `date_to?`, `action_prefix?` |
| `agent_timeline` | Activity | An agent's trail — its timesheet: every action it took, on which record, in which run, and whether the action is waiting on an approval. | `agent_member_id?`, `agent_run_id?`, `days?`, `action_prefix?`, `include_views?` |
| `record_history` | Activity | The change history of one record (who changed it, when, before/after). | `entity_type`, `entity_id` |

**Actions server — 19 tools** (writes; `†` = an approval policy may hold it for a person):

- `approval_approve`†, `approval_reject`, `approval_cancel`, `approval_policy_save`, `approval_policy_set_active`, `approval_policy_delete`†
- `model_save`, `model_set_status`
- `eval_set_save`, `eval_case_save`, `eval_case_promote_trace`, `eval_case_set_active`, `eval_run_start`, `eval_result_grade`, `eval_schedule_save`, `eval_alert_acknowledge`, `eval_alert_resolve`
- `ai_usage_post`†, `ai_usage_void`†

## 13. IT, estate & applications

Where the business runs: buildings, offices and desks, and the applications (built-in and external) that live at those locations.

| Tool | Server | Call it when | Key params |
| --- | --- | --- | --- |
| `estate` | Records | The whole picture: buildings, the offices (VMs) inside each, the desks, and what runs where. | `kind?`, `include_retired?`, `include_applications?` |
| `locations` | Records | Locations of one kind: which desks are online, which offices exist, when each was last seen and what version it runs. | `kind?`, `parent_location_id?`, `online_only?`, `siting?` |
| `get_location` | Records | One location's specs (platform, host reference, hostname, address, CPU, memory, storage), who lives there and its office manager, what it hosts, and its departments. | `location_id` |
| `who_is_where` | Records | Where a person or agent works: the office an agent runs in, or who is working remotely from a desk right now. | `member_id?`, `location_id?`, `online_only?` |
| `find_applications` | Records | What we run and where: by category, department or office, by health, and the gaps — no owner department, a stale health check, or an endpoint that needs a credential it has… | `category?`, `department_id?`, `location_id?`, `health?`, `gaps_only?` |
| `get_application` | Records | One application: where it runs, who owns it, its endpoints (kind, url, auth_kind, has_credential — never the credential itself — agent_reachable, mcp_surface_version), who… | `application_id`, `include_access?` |
| `my_applications` | Records | What I can reach and how — the first call an agent makes when a job needs an outside system: the endpoint it would actually use (url, kind, mcp_surface_version), and the… | `category?` |

**Actions server — 15 tools** (writes; `†` = an approval policy may hold it for a person):

- `location_set_office_manager`, `location_add_resident`, `location_remove_resident`, `location_save`, `location_move`, `location_rename`, `location_add_department`, `location_remove_department`, `location_retire`, `location_delete`
- `application_save`, `application_set_status`, `application_access_grant`, `application_access_revoke`, `application_health_check`

## 14. Cross-cutting tools

Tools that are not one function's: they reach across all of them.

| Tool | Server | Call it when | Notes |
| --- | --- | --- | --- |
| `records_search` | Records | The long tail — a question no named tool answers. One read-only `SELECT`/`WITH` over the `mcp_*` views. | 5 s timeout, 200-row cap, one statement, scoped to what the caller may see. Its own description still lists only the old study-app views; the business views are reachable too. |
| `activity_search` | Activity | The same, over the activity views. | Same guards. |
| `find_screen` | Actions | Turning "take me to the overdue invoices" into a screen. Searches all 243 registered screens. | Read-only. |
| `navigate` | Actions | Opening a screen once found. | Read-only; returns the URL. |

The Memory server's three tools (`recall`, `core_memory`, `session_search`) are in *AI workforce*, because that is whose memory they are; a person can call them too.

## 15. Legacy: community & certification study

The original members-vip app (exams, study plans, issues, events, resources). Its screens and its four action tools retired with the React cut-over on 2026-09-19, but the **read tools are still registered** and still answer. They serve no Business OS function; treat them as retirement candidates once the study modules are formally dropped.

| Tool | Server | Call it when |
| --- | --- | --- |
| `upcoming_calendar` | Records | Exams and community events on the community calendar. |
| `member_attempts` | Records | A member's exam attempts (dates, status, results where visible). |
| `study_buddies` | Records | Other members taking the same exam around the same time as the caller. |
| `retake_eligibility` | Records | When the caller is next allowed to retake an exam (from fail history + policy). |
| `my_certifications` | Records | The caller's certifications, expiry dates, and renewal windows. |
| `get_study_plan` | Records | A study plan with its items. Use for 'show me plan N' or reading a plan's approach. |
| `find_study_plans` | Records | Browse community study plans. from_passers=true limits to plans by members who passed & shared that exam (answers 'what did… |
| `plan_progress` | Records | Progress (completed vs. due) for a plan, or all the caller's plans if omitted. |
| `study_time_by_domain` | Records | The caller's study minutes and average confidence per domain (optionally one month). |
| `weak_domains` | Records | The caller's weakest domains for an exam: low confidence or little study time against the domain's weight. |
| `find_issues` | Records | Full-text search issues (M5: 'has anyone been stuck on this?'). |
| `issue_thread` | Records | An issue plus its replies (and which reply was accepted). |
| `unanswered_issues` | Records | Open issues with no replies (what needs answering / a workshop). |
| `find_resources` | Records | Search/browse study resources, ranked by endorsements (certified-member endorsements weighted highest). |
| `top_resources` | Records | Best resources for an exam per certified-member endorsements (M13/O11). |
| `event_details` | Records | An event with its RSVP list (who's coming). |
| `find_events` | Records | Community events (study groups, workshops, mock exams, …), optionally filtered. |
| `member_profile` | Records | A member's public directory profile. |
| `find_members` | Records | Search the member directory by name / taking an exam / certified in an exam. |
| `certified_members` | Records | Members who passed (and shared) an exam — who could help with it (M6). |
| `pass_rate` | Records | Community pass rate per exam (shared results only, anonymous). |
| `at_risk_members` | Records | Organizer-only: members with an upcoming exam but no plan, or no recent study. |
| `expiring_certifications` | Records | Organizer-only: certifications expiring within N days. |
| `first_activity_for_exam` | Activity | The caller's earliest study-related action for an exam (attempt/plan/session created with that exam_id) — answers 'when did I… |
| `reschedule_count` | Activity | How many times an exam attempt has been rescheduled (M17). |
| `since_last_login` | Activity | Public community activity since a time (new issues, replies, events, resources, plans) — 'what changed since I last logged in?'. |
| `community_activity_trend` | Activity | Organizer-only: weekly active members and action counts. |
| `moderation_audit` | Activity | Organizer-only: who hid, cancelled or edited what in the community, and when. |

## 16. Coverage and known gaps

- **Totals:** 107 business read tools across the eleven functions, 28 legacy read tools, 2 cross-cutting search tools (`records_search`, `activity_search`), and 333 action tools (plus `find_screen` and `navigate`) = 137 read tools and 335 on the Actions server.
- **Unbuilt actions:** 26 manifest actions are registered and findable but have no endpoint yet, so they are deliberately **not** exposed as tools.
- **Stale cross-reference:** `books_audit`'s description points at an activity tool `access_changes` that the Activity server does not register. The trail it means is reachable through `record_history` or `activity_search`.
- **Not on the public port:** `/mcp/actions` and `/mcp/memory` are localhost-only (only `/mcp/records` and `/mcp/activity` are proxied by the allow-list in `docs/deploy/apache-react-cutover.conf`). A person's own AI client can read but not write.

### How to keep this page true

It was produced by importing the four servers and listing their registered tools, plus `mcp/action_registry.json` for the actions. When a slice adds a tool, add it to the matching function here in the same session (the same rule as the requirements copies), and re-run the counts.
