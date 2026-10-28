# Business OS Schema

2026-09-17 · Edward Honour · **Draft for M1 review (build plan 1.4)**

> Source of truth: the migrations `db/030_*.sql` through `db/071_*.sql`.
> Derived from: `docs/business-os-questions.md` (287 questions). Next: the MCP tool surface (1.5) and the action manifest (1.6). All three get approved together at M1.
> **Not installed** on `maludb_os`. It was applied and tested on a throwaway copy (`maludb_os_schema_test`) only.

## Summary

- **33 migrations** add 141 tables and 142 read views to the existing 28 tables and 30 views. The cert-study modules are untouched and still answer through their own views.
- **Every business question** in the inventory maps to a table (record memory) or to `activity_log` (activity memory). The coverage table below lists them by section.
- **One visibility rule**, `app_can_see()`, governs every business record for humans and agents alike. It was tested with seven roles against the records MCP role (see Verification).

## Migration files

| File | Adds | Questions |
| --- | --- | --- |
| `030_business_foundation.sql` | Business roles on members, business settings, departments, module grants, record shares, tags, comments, tenant secrets, document numbering, visibility helpers | A1–A6, H1, H11 |
| `031_contacts_crm.sql` | Organizations, contacts, pipelines and stages, deals, interactions | C1–C16, DB4 |
| `032_projects_tasks.sql` | Projects, project members, milestones, tasks, dependencies, checklists | P1–P13, DB2, DB5 |
| `033_scheduling.sql` | Appointment types, bookable resources, appointments, crew, resource bookings, availability | K1–K10 |
| `034_tickets.sql` | Ticket categories, SLA policies, tickets, replies and internal notes | T1–T11 |
| `035_documents.sql` | Folders, documents, versions, links to any record; Postgres full-text search | DC1–DC8 |
| `036_time_log.sql` | Time entries (human hours) | W1–W7 |
| `037_sales_invoicing.sql` | Tax rates, catalog, quotes, invoices, payments + allocations, credit notes | S1–S14, S19, S20, DB1, DB3 |
| `038_payments_online.sql` | Payment providers, payment links, provider payments, webhook inbox, refunds, disputes, payouts | S15–S22 |
| `039_expenses.sql` | Flat categories, recurring expenses, expenses and bills, accountant exports | E1–E13 |
| `040_content_social.sql` | Channels, campaigns, content items, per-channel variants, media, metrics; attribution links | SM1–SM13, C12 |
| `041_notifications_business.sql` | Business notification kinds, preferences, email delivery log, suppressions, digests | N1–N5 |
| `042_agent_hr.sql` | Model registry, agent profiles, immutable config versions, tool grants, duties, HR events, reviews, escalations | H1–H13 |
| `043_locations_task_queue.sql` | The location tree (buildings → offices/VMs → desks) with its infrastructure facts, residents (human or agent), desk consent grants, the cross-location task queue | L1–L14 |
| `044_approvals.sql` | Approval policies, approval requests | AP1–AP8 |
| `045_prompt_ledger.sql` | Agent runs, prompt ledger, prompt payloads | PL1–PL9 |
| `046_evals.sql` | Eval sets, cases, runs, results, trace grades | EV1–EV8 |
| `047_ops_audit.sql` | Backup runs, restore rehearsals, data exports | X5, X6 |
| `048_activity_log_business.sql` | New activity sources; location, agent-run, approval and department links on `activity_log` | AP8, SM13, PL2, X1–X4 |
| `049_rls_triggers_business.sql` | RLS on every new table; `updated_at` triggers; append-only protection for ledger and HR history | all |
| `050_mcp_views_business.sql` | 89 record views + 3 activity views, generic entity visibility, grants | all |
| `051_seed_business_defaults.sql` | Business settings, member #1 as Owner, numbering, default pipeline, expense categories, proposed SLAs, the Office location (the minimum estate: one VM, no building) | — |
| `052_mcp_audit_views.sql` | `mcp_activity_unapproved_actions`, the activity-side approval audit (added with the tool surface, 1.5) | AP8, SM13 |
| `053_seed_approval_policies.sql` | 18 proposed default approval policies for agents: money out, deletions, external sends (added with the action manifest, 1.6) | AP2 |
| `054_timers_desk_imports.sql` | Running timers and staged desk imports, with their read views (gaps found by the action manifest, 1.6) | W2, DC8 |
| `055_estate_applications.sql` | The applications registry (systems, endpoints, access grants; every built-in module registered as an application), the three standing departments and their protection trigger, AI usage postings (prompt ledger → the books), eval schedules and degradation alerts | AC1–AC6, H14, H15, E14, E15, EV9–EV12 |
| `056_general_ledger.sql` | Chart of accounts, fiscal periods, journal entries and lines (balanced-and-open posting trigger, immutable once posted), posting rules, bank accounts, imported transactions, reconciliations | GL1–GL14 |
| `057_inbox_email.sql` | Mailboxes, threads, messages (full-text), attachments, per-member read state, routing rules | IB1–IB11 |
| `058_people_payroll.sql` | Employment profiles, compensation history, pay runs with items and lines, leave types, balances and requests | PE1–PE13 |
| `059_inventory_products.sql` | Products (feeding quote and invoice lines), stock locations, levels, movements, purchase orders and lines | IV1–IV12 |
| `060_esignature.sql` | Signature providers, requests, signers, append-only event trail | SG1–SG8 |
| `061_portal_forms.sql` | Forms, fields, submissions and their conversions, portal settings | PF1–PF10 |
| `062_reporting.sql` | Report definitions (a named MCP tool plus parameters), runs, schedules, dashboards and widgets | RP1–RP9 |
| `063_app_read_views.sql` | The app reads what the agents read: `mcp_*` views made reachable to the application role | — |
| `064_department_admin_visibility.sql` | `mcp_department_members` exposes `is_admin`, so "who administers this department?" is answerable (found building Contacts) | A1 |
| `065_related_name_masking.sql` | A record you may see must not name a record you may not: related names masked in list reads (found building Contacts) | — |
| `066_gapless_document_numbers.sql` | `invoices.number` / `credit_notes.number` nullable, assigned on issue, so the issued sequence is gapless; quotes keep creation-time numbering | S1, GL12 |
| `067_location_control_siting.sql` | `locations.control` (managed/unmanaged, inherited down the tree) and `locations.siting` (onsite/offsite); `location_effective_control()`, `location_allows_resident()` and the triggers that enforce them; `mcp_locations` rebuilt to carry both plus `allows_agents` | L1, L11, L12 |
| `068_location_functions_security_definer.sql` | The two db/067 functions made SECURITY DEFINER with a pinned search_path, so `app_records_ro` — which holds no base-table grants by design — can read `mcp_locations` again | L1, L11 |
| `069_location_platform_and_access.sql` | The platform vocabulary rewritten to five machine kinds (physical server with hypervisor / with OS, VPS, desktop, laptop); `operating_system`, `os_version`, `ssh_access`, `root_access` added and carried into `mcp_locations` | L2, L11, L12 |
| `070_agent_identity_and_prompt_library.sql` | `agent_profiles.description` / `role_key` / `profile_pic_url`; `system_prompts` + `system_prompt_versions` (immutable bodies); `agent_config_versions.system_prompt_id` / `system_prompt_version` with `job_description` kept as the resolved copy | H2, H3, H7 |
| `071_prompt_version_parameters.sql` | Model parameters move onto the prompt version (`parameters` jsonb + generated `temperature` / `max_tokens`), guarded by the same immutability trigger; `agent_config_versions.harness_config` becomes a trigger-written mirror of the cited version's parameters | H3, EV1 |
| `074_front_office_department.sql` | The Front Office: a fourth standing department, seeded and undeletable like the others, holding the root of the org chart — every other department is re-parented to it and a department saved with no parent is parented there by trigger; it seeds at the first active onsite office; `mcp_departments` carries `parent_name` | H14, H15 |
| `090_agent_profile_photos.sql` | An agent's photo becomes a file we hold: `agent_profiles.profile_pic_url` replaced by `profile_photo_path` / `mime` / `size_bytes` / `sha256` / `updated_at`, all-or-none and image types only; `mcp_agents` rebuilt so `profile_pic_url` is derived (the address that serves the photo, or NULL). First use of the tenant storage root db/035 describes | H2 |
| `091_voice_agent_kind.sql` | A third `agent_kind`, `voice`: answers inbound calls, its system prompt read by the telephony provider, and takes no part in delegation — so the one-level delegation rule is untouched; `agent_subagents_check()` names a voice agent instead of mislabelling it | H2, H5 |
| `093_voice_agent_phone.sql` | `agent_profiles.phone_number`: one E.164 number per voice agent, unique, refused on any other kind — what an inbound RetellAI call is matched on to decide whose system prompt answers it; carried into `mcp_agents` | H2, H5 |
| `094_agents_may_live_anywhere.sql` | Reverses db/067's residency gate at the owner's word: control is recorded and shown, never enforced. `location_allows_resident()` now allows people and agents at any office or desk (nobody in a building); the office-manager trigger is dropped. A hire no longer fails over how a location was recorded | L1, L11, H2 |
| `095_drop_location_control.sql` | Managed/unmanaged leaves the product at the owner's word: `locations.control` dropped, `location_effective_control()` dropped, `mcp_locations` rebuilt without `control` / `effective_control`. `siting` is untouched | L1, L11 |
| `096_hired_means_active.sql` | A hire lands on `active`: the agents still sitting in `candidate` are carried across exactly as the Activate button would have (latest version stamped activated, profile pointed at it, an `onboard` event recording it). `candidate` stays in the vocabulary for an activation refused or undone | H2, EV1 |
| `120_company_profile.sql` | Company Profile: singleton `company_profile` (story, facts, social links, logo/hero, published or not) beside `business_settings`, which keeps the identity; `company_profile_items` — a catalog item, an inventory product or a free-form showcase card, exactly the source its kind names, one card per record; `company_profile_media` (PNG/JPEG/WebP ≤ 5 MB, bytes on disk under the storage root); insiders-only views `mcp_company_profile` / `mcp_company_profile_items` (no `tax_id`, no storage path; a record's price only where the card shows it; an archived source hides its card); approval policy `company_profile.publish` for agents. *(db/097–119 belong to other slices and are described in their build specs.)* | CP1–CP5 |

## How visibility works

The request context is unchanged: the app and the MCP servers set `app.member_id` only. Everything else is looked up from that id, so the MCP servers need no changes and a role change takes effect on the next query.

| Role | Sees |
| --- | --- |
| Super-admin | Every business record |
| Dept-admin | Every record in the departments they administer, no grant needed. Outside them, exactly what a user sees |
| User (human or agent) | A module they're granted, limited to records in their departments or with no department, plus anything they own or are assigned |
| User + external flag | A module they're granted, whole and read-only (the accountant), plus records shared with them. Sharing an organization shares its invoices, quotes, projects and tickets. Never drafts, deals or internal ticket notes |

- **Record views** (`mcp_*`) embed the rule and are the only thing the records MCP role can read. It has no base-table grants, and RLS denies base tables to it anyway.
- **Polymorphic references** (tags, comments, document links, activity history) go through `app_can_see_entity()`, which checks the entity's own view. They can never be looser than the record itself.
- **Agent details** (job description, grants, budget, runs, prompts) are visible to holders of the HR or ledger module, the agent's manager, and the agent itself.
- **Hard walls, enforced in the views:**
    - Secrets and token hashes never appear in any view.
    - An agent sees only its own prompt payloads, never another agent's.
    - Agents never see eval cases, so they can't read their own test answers.
    - Member history (role and access changes) is visible to managers and the member only.

## Design decisions for approval

1. **Three business roles sit beside the cert-study roles** *(revised 2026-09-17)*. `members.business_role` is `super_admin`, `dept_admin` or `user`, and `member_kind` is human or agent; `members.role` (member, organizer) keeps working for the fork's modules. Member #1 becomes the super-admin and **nobody else is promoted by migration** — a dept-admin is made deliberately, by naming the departments they administer.
2. **External is a flag, not a role.** `members.is_external` marks the accountant, a contractor or a portal customer. They are users whose reach is what is granted or shared; a constraint refuses an external member any administrative role. This keeps the ladder at three while preserving the accountant's whole-module read access.
3. **A dept-admin's reach is department-shaped, in both directions.** `app_admin_department_ids()` returns the departments they are flagged admin of (`department_members.is_admin`) plus those they are the named manager of. Inside them `app_can_see()` returns true with no module grant; outside them they fall through to the ordinary user rule. Deliberately, a dept-admin does **not** implicitly hold every module — otherwise every record with no department would be open to every dept-admin.
4. **People follow the same rule.** `app_can_admin_member()` answers "do I administer this person" — true for a super-admin, and for a dept-admin when the member belongs to a department they administer. It gates contact details, module grants, tokens, notification preferences, time entries, timers and leave, so a Sales dept-admin sees Sales people's grants and nothing about Finance's.
5. **Agents are always users.** A constraint stops an agent from being any kind of administrator, so an agent can never see "everything". Wider reach comes only from explicit module grants.
6. **New tables beside the old modules, not conversions.** `projects`, `appointments`, `tickets`, `documents` and `time_entries` are new; `study_plans`, `community_events`, `study_issues`, `resources` and `study_sessions` keep running. There's no business data in the fork to migrate. Retiring the old tables is the separate decision already recorded.
7. **Departments scope staff visibility.** A record with no department is visible to every staff member holding that module. Put a record in a department to restrict it.
8. **Money is per-document currency, no FX.** Every money row carries its currency, and business settings hold the base currency. Invoice totals are stored and written by the app when lines change, so reports stay cheap.
9. **Every payment is a `payments` row.** Online charges live in `provider_payments` and create a `payments` row when they succeed. Allocations tie payments to invoices, so a payment with no allocation is the "unmatched payment" answer (S19).
10. **Human hours only in the time log.** Agent effort is measured by `agent_runs` and the prompt ledger, which carry `project_id`, `task_id` and `campaign_id` so AI spend rolls into project and campaign cost.
11. **Agent configuration is versioned and immutable.** Every change to job description, model, grants, schedule or budget is a new `agent_config_versions` row. Activating a version records its gating eval run, which makes "deployed without a passing eval" (EV8) a single query.
12. **Approvals link to what they allowed.** Approval requests record the activity row they executed, and `activity_log` rows carry the approval they ran under. "Above-threshold action with no approval" (AP8, SM13) is a single query.
13. **The activity log gets new columns but no foreign keys,** so it never blocks deleting or archiving other records. The ingestion bridge selects explicit columns, so MaluDB ingestion is unaffected.
14. **Prompt payloads live apart from ledger metadata.** Retention archives `prompt_payloads` while `prompt_ledger` keeps forever. The ledger, HR events, config versions and webhook events are append-only for the app role, apart from named columns.
15. **Not partitioned in v1.** `activity_log` and `prompt_ledger` stay single tables until volume says otherwise. The requirements' monthly partitioning becomes an ops task.
16. **Seeded later, on purpose:**
    - Approval policies were seeded with the action manifest (`053`), so their patterns match real log events.
    - Model registry rows wait for Phase 5, when model ids and prices get verified.
    - Tax rates depend on jurisdiction; the owner adds them.
17. **The estate is one tree, not two registries.** `locations` holds buildings (the hypervisor host or the premises), the offices inside them (one VM per office), and desks (one per enrolled desktop), with `parent_location_id` for the tree and one set of infrastructure columns (platform, external reference, hostname, address, CPU, memory, storage, always-on) describing all three. The alternative — a separate `hosts` table — would have split "where does this run" across two places and broken the one-audit-point rule the task queue depends on. The minimum estate is one office and nothing else — a building is optional and only recorded once a host carries several offices, so the seed creates the Office alone. A department works in an office (`departments.home_location_id`); an agent runs in one (`agent_profiles.home_location_id`); `location_residents` now takes any member, so humans working remotely from a desk appear in the same registry as the agents resident there.
18. **Applications are records, their credentials are not.** An application (the accounting system, the calendar, the CRM, this platform) resides at a location, belongs to a department, and is reached through endpoints. An endpoint carries a *reference* into `tenant_secrets`, never a value, and the view exposes only `has_credential`. Access is granted to a member or to a whole department; an agent needs a live grant **and** its tool grants, and only sees endpoints marked `agent_reachable`, so a human-only admin UI is never handed to an agent.
19. **Three departments exist in every tenant.** `HR`, `Accounting` and `Audit` are seeded with `is_system` and a `system_key`, and a trigger refuses to delete, archive or re-key them. They are renameable (a business may call HR "People Ops"), and they own work the platform already does: HR the agent employee records, Accounting the books and the AI spend meter, Audit the evals and the degradation watch.
20. **AI spend is bookkeeping, not a parallel universe.** `prompt_ledger` stays the subledger; `ai_usage_postings` rolls a period up per provider, model, department and agent and books it as one `expenses` row. The unique key on the period makes double-posting impossible, and the reconciliation question (E15) is a single query against the ledger it came from.
21. **Degradation is a record, not a report.** `eval_schedules` says what the Audit department runs and how often, with the regression delta that counts as slipping; `eval_alerts` records each breach, regression, drift or missed cycle until someone acknowledges and resolves it. An agent may read alerts about itself — it should know it is slipping — but still never reads eval cases.
22. **The ledger is the books; the subledgers stay put.** Invoices, payments, expenses and the prompt ledger keep their own tables and remain the operational record. `journal_entries` + `journal_lines` are what they post *into*, through `gl_posting_rules`, so a document can always be traced to its entry and back. A posted entry is immutable (trigger), must balance (trigger), and cannot post into a closed period (trigger) — which makes GL13 an audit query that returns nothing rather than a policy nobody enforces.
23. **Statutory payroll is out.** `pay_runs` record what was decided and paid, post to the ledger, and link to the time log for hourly work; tax tables and filing belong to the accountant or a payroll provider. Pay visibility is the tightest rule in the schema: your own record, your direct reports if you manage them, everything only with the `people` module for people you administer, or super-admin — and `app_can_see_person()` refuses agents outright, so no agent can read anyone's salary.
24. **Stock locations are not estate locations.** A warehouse, shop or van is where stock sits; an office is where software runs. `stock_locations.estate_location_id` links them when they coincide (the office cupboard) without merging two different ideas.
25. **A report is a tool call, not SQL.** `report_definitions` name an MCP tool plus fixed and prompted parameters. A report therefore runs as the member who runs it, over the same `mcp_*` views, and can never widen visibility — and the same definition answers from a screen, a schedule or the assistant.
26. **Forms are the inbound half of the portal.** The external flag plus `record_shares` already decide what a customer *sees*; `forms` and `form_submissions` decide what they can *send*, and `portal_settings` is the single switchboard for which sections the portal exposes.
27. **The shared inbox is the conversation; `email_messages` is the delivery.** Outbound mail still goes through MaluMail and is logged there (041); `mail_messages` links to that row rather than duplicating it, so "did it deliver?" and "what did we say?" are one join apart.
28. **Every built-in module is an application row** (`applications.is_builtin`, `applications.module`). `app_can_use_application()` therefore answers from the module grant for built-ins and from `application_access` for external systems — one permission system, two doors. A user granted `contacts` and `sales` reaches the CRM and Sales applications and nothing else; the bookkeeper reaches Books and Expenses.
29. **Aggregates live in tool SQL, not views.** Aging buckets, utilization and spend roll-ups are computed by the MCP tools over these views (`docs/business-os-mcp-tool-surface.md`). The one exception is the activity-side approval audit in 052, which must join activity to policies within one role.

## Question coverage

| Section | Answered from |
| --- | --- |
| Dashboard (DB1–DB7) | Aggregates over invoices, payments, expenses, deals, tasks, tickets, approval requests; DB6 and DB7 from `activity_log` + `agent_runs` |
| Contacts & CRM (C1–C16) | `organizations`, `contacts` (trigram + full-text), `deals` (+ `stage_entered_at`, last interaction), `interactions`, `record_shares`; C13–C15 from activity |
| Sales & invoicing (S1–S22) | `invoices` (+ `balance_due`, days overdue), `invoice_lines`, `quotes`, `payments`, `payment_allocations`, `credit_notes`, `payment_links`, `provider_payments`, `refunds`, `disputes`, `payouts`; S12, S13, S21 from activity |
| Bookkeeping (GL1–GL14) | `gl_accounts`, `fiscal_periods`, `journal_entries`, `journal_lines`, `gl_posting_rules`, `bank_accounts`, `bank_transactions`, `bank_reconciliations`; statements and the trial balance are aggregates over `mcp_journal_lines` |
| Shared inbox (IB1–IB11) | `mailboxes`, `mail_threads`, `mail_messages` (tsvector), `mail_attachments`, `mail_thread_reads`, `mail_rules`; delivery from `email_messages`; IB11 from activity |
| People & payroll (PE1–PE13) | `employment_profiles`, `compensation_changes`, `pay_runs`, `pay_run_items`, `pay_run_lines`, `leave_types`, `leave_balances`, `leave_requests`; PE13 from activity |
| Products & inventory (IV1–IV12) | `products`, `stock_locations`, `stock_levels`, `stock_movements`, `purchase_orders`, `purchase_order_lines`, `product_id` on invoice and quote lines; IV12 from activity |
| E-signature (SG1–SG8) | `signature_providers`, `signature_requests`, `signature_signers`, `signature_events`; SG8 from activity |
| Portal & forms (PF1–PF10) | `forms`, `form_fields`, `form_submissions`, `portal_settings`, plus `record_shares` and `module_grants` for what a customer sees; PF9, PF10 from activity |
| Reporting (RP1–RP9) | `report_definitions`, `report_runs`, `report_schedules`, `dashboards`, `dashboard_widgets`; RP9 from activity |
| Expenses (E1–E15) | `expenses`, `expense_categories`, `recurring_expenses`, `accountant_exports`, `ai_usage_postings` (the prompt ledger posted to the books); receipts via `documents`; E11 from activity |
| Projects & tasks (P1–P13) | `projects`, `tasks`, `task_dependencies`, `milestones`, `project_members`, `time_entries`, `expenses`, `agent_runs` / `prompt_ledger` for AI spend; P10–P12 from activity |
| Scheduling (K1–K10) | `appointments`, `appointment_assignees`, `appointment_resources`, `availability_blocks` (range indexes), `invoice_lines.appointment_id`; K9, K10 from activity |
| Tickets (T1–T11) | `tickets` (stamped SLA due times, first response, reopen count), `ticket_messages` (full-text); T10 from activity |
| Documents (DC1–DC9) | `documents` (full-text over title, body, extracted text), `document_versions`, `document_links`, `folders`, `departments.handbook_document_id`; DC7 from activity; DC9 is desk-local by design |
| Time (W1–W7) | `time_entries` (billable, rate snapshot, approval, lock, invoice line); W7 from activity |
| Team & access (A1–A10) | `members`, `department_members`, `module_grants`, `record_shares`, `invitations`, `mcp_access_tokens`; A7–A9 from activity |
| Notifications (N1–N5) | `notifications`, `notification_preferences`, `email_messages`, `email_suppressions`, `digest_sends` |
| Departments & agent HR (H1–H15) | `departments`, `agent_profiles`, `agent_config_versions`, `agent_tool_grants`, `agent_duties`, `hr_events`, `performance_reviews`, `agent_escalations`, `agent_runs`; `departments.is_system` / `system_key` / `home_location_id` / budget for H14, H15; H6, H13 from activity |
| Estate (L1–L14) | `locations` (tree via `parent_location_id`; kind building/office/desk; platform, external ref, hostname, address, specs, presence, last seen, version), `location_residents` (human or agent), `departments.home_location_id`, `agent_profiles.home_location_id`, `consent_grants`, `location_tasks` (status timestamps for queue wait) |
| Applications (AC1–AC6) | `applications` (category, office, owning department, criticality, health, cost link), `application_endpoints` (kind, auth, secret reference only), `application_access` (member or department, capability, expiry), `app_can_use_application()` |
| Approvals (AP1–AP8) | `approval_policies`, `approval_requests`; AP7 from activity; AP8 joins `activity_log.approval_request_id` |
| Prompt ledger (PL1–PL9) | `prompt_ledger` (tokens, cache, latency, cost, status, location), `prompt_payloads`, `agent_runs`, `model_registry`; PL2 joins `activity_log` on `request_id` |
| Evals (EV1–EV12) | `eval_sets`, `eval_cases` (promoted-trace origin), `eval_runs` (+ baseline), `eval_results`, `trace_grades`, `eval_schedules`, `eval_alerts`; EV8 joins `agent_config_versions.gating_eval_run_id` |
| Content & social (SM1–SM13) | `channels`, `campaigns`, `content_items`, `content_variants` (calendar, publish result), `content_metrics`, attribution columns on organizations, contacts and deals; SM11 cost from expenses + time + `agent_runs`; SM12 from activity |
| Tenant & audit (X1–X8) | `activity_log` (history, actor, source, agent run), `backup_runs`, `restore_rehearsals`, `data_exports`, `mcp_access_tokens` |

## Verification (on `maludb_os_schema_test`)

- **Migrations:** all 33 apply in order with `ON_ERROR_STOP` on a fresh clone of `maludb_os` (re-verified 2026-09-17 after the back-office modules). The seed file re-runs cleanly, and the views file re-applies cleanly.
- **Coverage checks:** every table has RLS, the read roles hold no base-table grants, and every `updated_at` table has its trigger. Foreign keys used in lookups or cascading deletes have indexes; unindexed ones are audit columns only (`created_by` and similar).
- **Secrets:** the records MCP role is denied `tenant_secrets` and base tables such as `invoices`. The cert-study `mcp_exams` view still answers.
- **Role fixture (re-run 2026-09-17 on the three-role model),** queried as the records MCP role. Departments Sales and Ops, one organization and one invoice in each plus one with no department:

| Member | Administers | Organizations | Invoices | Team emails visible |
| --- | --- | --- | --- | --- |
| Super-admin | every department | all 3 | 3 | all 7 |
| Dept-admin of Sales (also a member of Ops, no grants) | Sales | Sales only | 1 | 3 (self + the two Sales members) |
| User, Sales (contacts + sales) | — | Sales + no-department | 2 | 1 (self) |
| User, Ops (contacts only) | — | Ops + no-department | 0 | 1 (self) |
| External user (sales + expenses, read) | — | none | 3 (whole module, the accountant) | 0 |
| Agent, Sales (contacts) | — | Sales + no-department | 0 | 1 (self) |

  Note the second row: administering Sales does not reveal Ops, and *belonging* to Ops without a module grant reveals nothing there either.

- **Earlier seven-role fixture** (pre-revision role names), kept for the module-by-module coverage it proved:

| Member (roles revised 2026-09-17) | Organizations | Deals | Invoices | Internal notes | Prompt payloads | Eval cases |
| --- | --- | --- | --- | --- | --- | --- |
| Super-admin | all 3 | 3 | 6 | 1 | 2 | 2 |
| User, Sales dept (contacts + sales) | Sales org + no-dept org | 2 | 4 | 0 | 0 | 0 |
| User, Ops dept (contacts only) | Ops org + no-dept org | 2 | 0 | 0 | 0 | 0 |
| External user (sales, read) | none | 0 | 3 (sent only) | 0 | 0 | 0 |
| External user (Acme shared) | Acme | 0 | 1 | 0 | 0 | 0 |
| Agent (user), Sales dept | Sales org + no-dept org | 2 | 4 | 0 | 1 (own) | 0 |
| Agent (user), Ops dept | Ops org + no-dept org | 2 | 0 | 0 | 1 (own) | 0 |

- **Audit queries:** the EV8 and AP8 checks run against the schema and return 0. `next_document_number('quote')` returns `Q-00001`.
- **Standing departments:** Front Office, HR, Accounting and Audit seed once, refuse deletion and archival, and accept a rename. The Front Office holds `parent_id IS NULL` and every other department reports to it: an insert with no parent is parented there, and an attempt to give the Front Office a parent is nulled back out (db/074).
- **Estate fixture:** the seed builds `Main Building` → `Office`, with the four standing departments homed in the Office and the platform registered as an application there. Queried as the records MCP role with an accounting application that has an MCP endpoint (secret-backed) and a human-only UI endpoint: the Owner sees both endpoints, a staff member with no grant sees the application but no endpoint and `i_can_use = false`, and the Accounting agent (granted through its department) sees the MCP endpoint only, with `capability = write` and `has_credential = true`. `tenant_secrets` stays denied to the read role.
- **AI usage postings:** a second posting for the same period, provider, model, department and agent is rejected by the unique key (`NULLS NOT DISTINCT`), so a period cannot be booked twice.
- **Built-in application access:** with 21 built-in applications registered at the Office, a staff member granted `contacts` + `sales` reaches exactly CRM and Sales; an agent granted `books` + `expenses` reaches exactly Books and Expenses. Both see the other 19 listed with `i_can_use = false`.

## Open points for this review

1. **Install timing:** install the schema on `maludb_os` right after M1 approval, or wait until the shell conversion starts? Recommendation: at approval, since everything is additive and the cert-study modules were verified untouched.
2. **Department default:** records with no department are visible to all staff holding the module. The stricter alternative is owner-only until a department is set. Recommendation: keep the open default for a small business.
3. **Estate depth:** the tree is building → office → desk, two levels plus desks. Racks, sites or regions would need a third. Recommendation: keep two levels; `parent_location_id` already allows deeper nesting if a tenant needs it, without a schema change.
4. **Physical assets:** vehicles, rooms and equipment stay in `bookable_resources` (scheduling), not in the estate tree, because they are booked rather than run on. Applications and locations are infrastructure; resources are capacity. Recommendation: keep them apart, and revisit if a tenant wants one "properties" view over both.
5. **Who posts AI spend:** the roll-up is a scheduled draft; posting it to the books is an explicit action (`ai_usage_post`, money-approval category). The alternative is automatic monthly posting. Recommendation: keep it explicit for the first tenants, so the accountant sees the number before it lands.
6. **Still open from earlier reviews:** social publishing depth, default approval thresholds, prompt-payload retention period. *(First payment provider decided 2026-09-18: Stripe.)*
