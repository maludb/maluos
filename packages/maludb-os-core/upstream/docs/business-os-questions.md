# Business OS Question Inventory

2026-09-17 · Edward Honour · **Draft for review (build plan 1.3)**. Review decisions of 2026-09-17 applied (see the last section).

> Requirements: `docs/business-os-requirements.md` · Build plan: `docs/business-os-build-plan.md`
> Next steps: the schema (1.4) comes from this list, and the MCP tool surface (1.5) maps every question to a tool.
> A question that no memory can answer is a modeling bug. It gets fixed here, before anything is built.

## How to read this

**Mem**: which memory answers the question.

| Code | Memory | Served by |
| --- | --- | --- |
| R | Record memory: the tenant's PostgreSQL database, current state | records MCP (`mcp_*` views) |
| A | Activity memory: the `activity_log` stream in MaluDB (who did what, when, before and after) | activity MCP |
| R+A | Needs both: current state joined to its history | both servers, or one tool that joins them |
| D | Desk-local resources (files, folders) on an enrolled desktop | desk local tools, never the server |

**Asked by**: SA = super-admin · DA = dept-admin (for the departments they administer) · U = user · Ex = external user (accountant, contractor, client portal) · Ag = an AI agent asking for itself (an office manager, a resident agent or the AMA agent). Visibility follows the asker: an agent sees what its member row sees, never more.

**Rule for records:** every question is scoped by RLS. For a user, "who owes us?" means "who owes us, among the records I can see"; for a dept-admin it means their departments plus whatever their grants add.

---

## 1. Dashboard

Implies: aggregates from the modules only; the dashboard stores no data of its own.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| DB1 | How are we doing right now: billed, collected and spent this month vs last month? | R | SA, DA |
| DB2 | What needs my attention today (overdue invoices, tasks due, open tickets, approvals waiting)? | R | SA, DA, U |
| DB3 | What's our cash position trend over the last 12 months (collected minus spent)? | R | SA |
| DB4 | What's the pipeline worth, and how much is likely to close this month? | R | SA, DA |
| DB5 | How busy is the team this week (booked hours, open tasks per person)? | R | DA |
| DB6 | What changed in the business since I last logged in? | A | SA, DA, U |
| DB7 | What did the AI agents do today, and did anything need a human? | R+A | SA, DA |

## 2. Contacts & CRM (the exemplar slice)

Implies: organizations, people (who can belong to an organization), contact roles (customer, vendor, lead, partner), deals with stages, a pipeline, owner and department, interactions (calls, emails, meetings, notes), tags, a portal-access link to an External member.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| C1 | Find a contact or organization by name, email, phone or fragment. | R | all |
| C2 | Who is the main contact at organization X, and how do I reach them? | R | all |
| C3 | Who are our customers, vendors, leads or partners (filtered by type, tag or owner)? | R | SA, DA, U |
| C4 | Where does each open deal stand (stage, value, expected close, owner)? | R | SA, DA, U |
| C5 | Which deals are expected to close this month or quarter, and how much are they worth? | R | SA, DA |
| C6 | Which deals have gone quiet (no interaction in N days)? | R+A | DA, U, Ag |
| C7 | What's our win rate and average deal size by stage, source or owner? | R | SA, DA |
| C8 | When did we last talk to X, and what was said? | R | all |
| C9 | What's the full relationship history with organization X (deals, invoices, projects, tickets, interactions)? | R | SA, DA, U |
| C10 | Who owns this contact or deal, and in which department? | R | all |
| C11 | Which contacts have no owner, or have duplicate records? | R | DA |
| C12 | Where did our leads come from this quarter (source breakdown)? | R | SA, DA |
| C13 | How long do deals sit in each stage? | A | SA, DA |
| C14 | Who changed this deal's stage or value, and when? | A | SA, DA |
| C15 | Who created or merged this contact, and what did it look like before? | A | DA |
| C16 | Which external members (client portal) can see this organization's records? | R | SA, DA |

## 3. Sales & invoicing

Implies: quotes and quote lines, invoices and invoice lines, tax rates, payment terms, payments (partial allowed; method: manual record or online), credit notes, invoice status history (draft, sent, viewed, partially paid, paid, void), customer statements, numbering sequences. **Online collection is in v1 (decided):** payment-provider accounts per tenant (credentials in tenant secrets, never exposed through MCP), payment links or checkout sessions per invoice, provider events received by webhook (succeeded, failed, refunded, disputed), refunds, payouts with provider fees. The payment provider stays behind an adapter; which provider comes first is an open point below.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| S1 | What did we invoice last month (or in any period), in total and by customer? | R | SA, DA, Ex |
| S2 | Who owes us money, and how overdue are they (aging buckets 0–30, 31–60, 61–90, 90+)? | R | SA, DA, Ex, Ag |
| S3 | What's the status of invoice #N (sent, viewed, paid, balance due)? | R | all |
| S4 | What have we collected this month, and from whom? | R | SA, DA, Ex |
| S5 | Which quotes are outstanding, and which have expired without a decision? | R | DA, U |
| S6 | What's our quote-to-invoice conversion rate? | R | SA, DA |
| S7 | Who are our top customers by revenue this year? | R | SA, DA |
| S8 | What does customer X's statement look like (invoices, payments, balance)? | R | SA, DA, Ex |
| S9 | How much tax did we charge in a period (by rate)? | R | SA, Ex |
| S10 | Which invoices are for a given project or deal? | R | DA, U |
| S11 | What's our average days-to-pay, overall and per customer? | R+A | SA, DA |
| S12 | When was invoice #N sent, reminded, viewed and paid? | A | SA, DA, U |
| S13 | Who voided, edited or credited this invoice, and what changed? | A | SA, Ex |
| S14 | Which invoices were created or sent by an agent rather than a human? | A | SA, DA |
| S15 | Which online payments failed, and for which invoices? | R | SA, DA, Ag |
| S16 | Which invoices have an unpaid payment link older than N days? | R | DA, Ag |
| S17 | What refunds and disputes are open, and how much is at stake? | R | SA, DA |
| S18 | What did the payment provider pay out this month, and how much went to fees? | R | SA, Ex |
| S19 | Does every provider payment match an invoice (unmatched or duplicate payments)? | R | SA, Ex |
| S20 | Which invoices were paid online vs recorded manually? | R | SA, DA |
| S21 | When did the customer open the payment link, and when did the provider confirm payment? | A | DA, U |
| S22 | Who issued this refund, and was it approved? | R+A | SA, Ex |

## 4. Expenses & money out

Implies: vendors (contacts with the vendor role), expense entries, flat categories (decided: no double-entry ledger in v1; accountant export instead), receipts (file attachments via Documents), payment method, project or customer allocation (billable flag), recurring expenses, bills due.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| E1 | What did we spend this month (or in any period), by category? | R | SA, DA, Ex |
| E2 | What did we spend on X (a category, a vendor or a free-text match)? | R | SA, DA, Ex |
| E3 | Who are our biggest vendors this year? | R | SA, DA |
| E4 | Which bills are due in the next N days? | R | SA, DA, Ag |
| E5 | Which expenses are missing a receipt? | R | DA, Ex |
| E6 | What are our recurring costs (subscriptions, rent) per month? | R | SA |
| E7 | How much did project or customer X cost us (expenses, hours and AI spend), and how much of it is billable? | R | SA, DA |
| E8 | Which billable expenses haven't been invoiced yet? | R | DA |
| E9 | How does spending this month compare to our 3-month average, per category? | R | SA |
| E10 | What did I submit, and what's its status? | R | U |
| E11 | Who entered, approved or changed this expense? | A | SA, Ex |
| E12 | What money-out actions did agents take or request this month? | R+A | SA, DA |
| E13 | What's in the accountant export for a period (invoices, payments, expenses, fees, by category), and when was it last pulled? | R+A | SA, Ex |
| E14 | What did the AI workforce cost us this period, by provider, model, department and agent — and is it posted to the books? | R | SA, DA, Ex |
| E15 | Does the AI expense posted for a period reconcile to the prompt ledger it came from? *(must always agree; this is the audit check)* | R | SA, Ex |

## 5. Projects & tasks (converts plans + plan items)

Implies: projects (customer, deal link, department, status, budget hours and money, dates; cost includes AI spend from ledger entries tagged with the task, decided), tasks (assignee = any member, human or agent; due date; status; priority; dependencies; checklist), milestones, comments.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| P1 | What projects are active, for whom, and are they on track? | R | SA, DA, U |
| P2 | What's on my plate this week (my tasks by due date)? | R | U, Ag |
| P3 | What's overdue, across the business or per person, department or project? | R | DA, Ag |
| P4 | Who is working on project X, and what is each of them doing? | R | DA, U |
| P5 | What's blocking project X (blocked tasks, unmet dependencies)? | R | DA, U, Ag |
| P6 | How far along is project X (tasks done vs total, hours used vs budget)? | R | SA, DA, Ex |
| P7 | Which tasks are assigned to agents, and what's their status? | R | DA |
| P8 | Which projects are over budget in hours or money (including AI spend)? | R | SA, DA |
| P13 | How much AI spend went into project X, by agent and task? | R | SA, DA |
| P9 | What milestones are coming up in the next 2 weeks? | R | DA, U |
| P10 | Who reassigned or rescheduled this task, and how many times? | A | DA |
| P11 | How long do tasks of type X usually take from creation to done? | A | DA |
| P12 | What happened on project X last week? | A | SA, DA, Ex |

## 6. Scheduling & calendar (converts events + calendar + iCal)

Implies: appointments and jobs (type, customer, location/address, start and end), crew assignments (members, including agents for virtual duties), resources (rooms, vehicles, equipment), recurrence, availability or blocked time, and the per-member iCal feed.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| K1 | What's happening this week, and who is booked on what? | R | all |
| K2 | What's my schedule today or tomorrow? | R | U, Ag |
| K3 | Who's free on Thursday afternoon for a 2-hour job? | R | DA, Ag |
| K4 | Which appointments are with customer X, past and upcoming? | R | DA, U |
| K5 | Is there a double-booking or conflict for a person or resource? | R | DA, Ag |
| K6 | How many jobs of each type did we do this month? | R | SA, DA |
| K7 | Which completed jobs haven't been invoiced? | R | SA, DA |
| K8 | When is our next appointment with X? | R | all |
| K9 | Who cancelled or rescheduled this appointment, and when? | A | DA |
| K10 | How often does customer X reschedule? | A | DA |

## 7. Tickets & requests (converts issues)

Implies: tickets (origin: internal, portal or email-in later; requester contact; department; assignee; priority; SLA target; status), replies and internal notes, links to project or customer, satisfaction (optional, later).

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| T1 | What tickets are open, by department, assignee or priority? | R | DA, U, Ag |
| T2 | What's assigned to me? | R | U, Ag |
| T3 | Which tickets are breaching or close to breaching SLA? | R | DA, Ag |
| T4 | What has customer X asked us for, and what's still open? | R | DA, U, Ex |
| T5 | Which tickets have no reply yet? | R | DA, Ag |
| T6 | Have we seen this problem before, and how was it resolved? | R | U, Ag |
| T7 | What are the most common ticket categories this month? | R | SA, DA |
| T8 | What's our average first-response and resolution time, per department? | R+A | SA, DA |
| T9 | What's the status of my request? (client portal) | R | Ex |
| T10 | Who reassigned, escalated or closed this ticket, and when? | A | DA |
| T11 | Which tickets did agents resolve without a human, and were any reopened? | R+A | SA, DA |

## 8. Documents & knowledge (converts resources)

Implies: folders, documents (file storage, versions, owner, department, sharing), links from documents to any record (contact, invoice, project, ticket, expense, content post), procedures/handbook pages (including department handbooks that agents load at onboarding), PostgreSQL full-text index (decided for v1; MaluDB semantic indexing is a Phase 4 enhancement).

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| DC1 | Where is the file for X (by name, content or linked record)? | R | all |
| DC2 | What's our procedure for X? | R | U, Ag |
| DC3 | What documents are attached to customer, project or invoice X? | R | DA, U, Ex |
| DC4 | What's in department X's handbook? | R | U, Ag |
| DC5 | Which documents are shared with this external member? | R | SA, DA |
| DC6 | What changed between version 2 and version 3 of this document? | R | DA, U |
| DC7 | Who uploaded, edited, shared or deleted this document? | A | SA, DA |
| DC8 | Which documents were imported from a desk, and by whom? | R+A | SA, DA |
| DC9 | What's in the spreadsheet or folder on my desk that I opted in? | D | U, Ag |

## 9. Time & work log (converts study_log)

Implies: time entries (member, project/task/customer/ticket, duration, date, billable flag, rate, note), approval or lock status, invoiced link. Agent "time" is measured by the prompt ledger and activity, not by time entries.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| W1 | Where did the hours go last week, by project, customer and person? | R | SA, DA |
| W2 | How many hours did I log this week, and on what? | R | U |
| W3 | How many billable hours are unbilled, per customer? | R | SA, DA |
| W4 | Who hasn't logged time this week? | R | DA |
| W5 | What's our utilization (billable vs total hours) per person? | R | SA, DA |
| W6 | How many hours has project X used against its budget? | R | DA, Ex |
| W7 | Who edited a time entry after it was approved or invoiced? | A | SA, Ex |

## 10. Team & access (converts members, settings, 2FA, tokens)

Implies: members (human or agent, role, status), invitations, department membership, module grants, personal MCP tokens (label, scope, last used), 2FA status, sessions.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| A1 | Who works here, in what role and department? | R | all |
| A2 | What can member X access (role, departments, module grants, shared records)? | R | SA, DA |
| A3 | Who has been invited but hasn't joined? | R | SA, DA |
| A4 | Who doesn't have 2FA enabled? | R | SA |
| A5 | Which MCP tokens exist, whose are they, and when were they last used? | R | SA, DA (own: U) |
| A6 | Which external members exist, and what's shared with each? | R | SA, DA |
| A7 | Who changed member X's role or grants, and when? | A | SA |
| A8 | When did X last log in, and from where? | A | SA |
| A9 | Which tokens called which MCP tools this week? | A | SA |
| A10 | Who invited X, and when did they first log in? | R+A | SA, DA |

## 11. Notifications & digest

Implies: notifications (recipient, type, source record, read state), per-member notification rules/preferences, digest sends via MaluMail (with suppression state).

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| N1 | What needs my attention (unread notifications, grouped by type)? | R | all |
| N2 | What was in my digest this morning? | R | all |
| N3 | Which notifications am I subscribed to, and how do they reach me? | R | all |
| N4 | Which emails bounced or are suppressed? | R | SA, DA |
| N5 | Was X notified about Y, and did they open it? | R+A | DA |

## 12. Departments & agent HR

Implies: departments (name, manager, parent), department membership (member, department, primary flag), agent employment profiles (job description versions, manager, model registry key, tool and action grants, schedule of duties, spend budget, status: candidate, active, suspended or offboarded), HR events (hire, onboard, adjust, review, offboard), performance reviews.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| H1 | Who, human or AI, works in department X, and who manages it? | R | all |
| H2 | What agents do we employ, what does each do, and who manages each? | R | SA, DA |
| H3 | What is agent X's job description, model, tool grants and schedule? | R | SA, DA, Ag (self) |
| H4 | How is agent X performing: actions taken, tasks closed, escalations, spend vs budget, eval scores? | R+A | SA, DA |
| H5 | Which agents are over or near their spend budget this month? | R | SA, DA |
| H6 | What did agent X do last week, and why? | A | SA, DA |
| H7 | What changed in agent X's job description, tools or model over time, and who changed it? | R+A | SA, DA |
| H8 | Which agents escalate most, and about what? | R+A | DA |
| H9 | What are my duties today, and what's my remaining budget? | R | Ag (self) |
| H10 | Who is my manager, and what can I do without approval? | R | Ag (self) |
| H11 | Which departments have no manager or no members? | R | SA |
| H12 | When was agent X hired, suspended or offboarded, and by whom? | A | SA |
| H13 | What's the full archived trail of an offboarded agent? | A | SA |
| H14 | Which department does each of the four standing duties — Front Office, HR, Accounting, Audit — who manages each, and who reports to whom? | R | SA, DA, Ag |
| H15 | Which office does department X work in, which applications does it own, and what is its budget against actual spend? | R | SA, DA |

## 13. The estate: buildings, offices, desks & applications

Implies two registries that together describe where the business exists.

**Locations** are a tree: a *building* (the hypervisor host or the physical premises), the *offices* inside it (one VM per office — departments work in them and agents run in them), and the *desks* (one per enrolled desktop, where a human and their resident agents work remotely). Each location carries its infrastructure facts (platform, external reference such as a Proxmox node or VMID, hostname, address, CPU/memory/storage, always-on), its presence and last-seen, its residents (human or agent, with the office manager flagged), and its app version. The cross-location task queue and desk consent grants are unchanged (requester member and location, target location, assigned agent, type, payload reference, status, timestamps; grants are standing or one-off with expiry).

**Applications** are the systems that reside at a location — the accounting system, the calendar, the CRM, mail, this platform itself. Each has a category, an owning department, an accountable human, the location it runs on, its criticality and health, what it costs (a link to the recurring expense), one or more endpoints (MCP, HTTP API, database, filesystem, UI — with an auth kind and a reference to a tenant secret, never the secret), and access grants to members or whole departments. An agent reaches an application only with a live grant, and only through endpoints marked agent-reachable.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| L1 | What locations do we have, who owns each, and which are online now? | R | SA, DA |
| L2 | Who — human or agent — works at location X, and which agent is its office manager? | R | SA, DA, Ag |
| L3 | What's the status of the task I sent to location X? | R | all |
| L4 | What's queued for my desk while it was offline? | R | U, Ag |
| L5 | Which tasks failed or were refused this week, and why? | R | SA, DA |
| L6 | Who has standing permission to send tasks to my desk, and for what? | R | U (desk owner), SA |
| L7 | Which cross-location tasks touched my desk, and who requested them? | R+A | U (desk owner) |
| L8 | How long do tasks wait in the queue, per location? | R | SA |
| L9 | When was desk X last online, and what version is it running? | R | SA, DA |
| L10 | Which agent at which location should handle this request? | R | Ag (office manager) |
| L11 | What does our estate look like — which buildings, which offices in each, which desks — and what runs where? | R | SA, DA |
| L12 | What are office X's specs (platform, host reference, address, CPU, memory, storage) and what does it host? | R | SA, DA |
| L13 | Which office does agent X run in, and which of our people are working remotely from a desk right now? | R | SA, DA |
| L14 | Who created, moved, retired or re-specced a location, and when? | A | SA |
| AC1 | What applications do we run, in which office, owned by which department, and are they up? | R | SA, DA, U |
| AC2 | Which applications can I reach, with what capability, and through which endpoint? | R | U, Ag (self) |
| AC3 | Who and which departments have access to application X, at what capability, and when does it expire? | R | SA, DA |
| AC4 | Which applications have no owner, no health check in N days, or a credential that is missing or expiring? | R | SA, DA |
| AC5 | What do our applications cost per month, and against which department? | R | SA, Ex |
| AC6 | Who granted or revoked access to application X, and when? | A | SA, DA |

## 14. Approvals

Implies: threshold policies (action type, amount, scope: agent, department or tenant), approval requests (requesting member, action from the manifest, parameters, amount, approver, status, decision note, expiry), linked activity. Default thresholds are an **open question** (proposed: money out, deletions, external sends).

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| AP1 | What's waiting for my approval? | R | SA, DA |
| AP2 | Which actions require approval for agent X or department Y (the policy)? | R | SA, DA, Ag (self) |
| AP3 | What did I approve or reject this month? | R | SA, DA |
| AP4 | Which requests expired without a decision? | R | SA |
| AP5 | What's the status of my approval request? | R | U, Ag |
| AP6 | How long do approvals take, per approver? | R | SA |
| AP7 | Who changed the approval thresholds, and when? | A | SA |
| AP8 | Did any above-threshold action run without an approval? *(must always return none; this is the audit check)* | R+A | SA |

## 15. Prompt ledger & agent runtime

Implies: model registry (model key, provider, harness, config, price per token), prompt ledger entries (timestamp, agent, location, harness plus SDK version, provider plus model, request id linking to `activity_log`, token counts including cache read and write, latency, cost, status), payload store (full context and response, subject to retention policy), provider credentials (per tenant, never exposed through MCP). Entries carry an optional `task_id` / `project_id` so AI spend rolls up into project cost (decided). All of this is **R**: the ledger lives in the tenant database, per the requirements.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| PL1 | What did the AI spend this month, by agent, model and provider? | R | SA, DA |
| PL2 | Show the full prompt and response behind action X (activity entry → ledger). | R+A | SA, DA |
| PL3 | Which calls failed, timed out or hit rate limits this week? | R | SA |
| PL4 | What's the average latency and token use per agent or model? | R | SA |
| PL5 | How much are we saving from prompt caching? | R | SA |
| PL6 | Which models are available, and what does each run in (harness registry)? | R | SA, DA |
| PL7 | Which calls did agent X make during task Y? | R | SA, DA |
| PL8 | Which ledger payloads are due for archiving under retention policy? | R | SA |
| PL9 | Which calls ran at a desk location, and which at the Office? | R | SA |

## 16. Evaluations

Implies: standing schedules owned by the Audit department (cadence, sample size, the regression delta that raises an alert) and the alerts they raise (threshold breach, regression, trace drift, missed cycle; open, acknowledged or resolved), on top of: eval sets (per agent or role), eval cases (input, rubric, expected behavior, origin: authored or promoted from a ledger trace), eval runs (trigger: hiring, change control, continuous or manual; model and harness under test; config snapshot), case results (score, grader, notes).

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| EV1 | Did candidate model/harness X pass the evals for role Y? | R | SA, DA |
| EV2 | What's agent X's eval score trend over time? | R | SA, DA |
| EV3 | Which eval cases fail most, across agents? | R | SA, DA |
| EV4 | Did the last change to agent X regress anything, and which cases? | R | SA, DA |
| EV5 | Which cases were promoted from real traces, and from which ledger entry? | R | SA, DA |
| EV6 | Which sampled production traces graded poorly this week? | R | SA, DA |
| EV7 | Who changed an eval set or rubric, and when? | A | SA |
| EV8 | Was agent X's latest change deployed without a passing eval run? *(must return none; this is the audit check)* | R+A | SA |
| EV9 | Which eval sets are on a standing schedule, at what cadence, and when does each run next? | R | SA, DA |
| EV10 | Which agents are degrading — open alerts for a threshold breach, a regression against baseline, or drift in sampled traces? | R | SA, DA |
| EV11 | Am I slipping, and against what baseline? | R | Ag (self) |
| EV12 | Which scheduled evaluation cycles were missed, and which alerts are still unacknowledged? | R | SA |

## 17. Content & social (in v1, decided)

Implies: channels (connected social accounts, newsletter or blog, per tenant; credentials in tenant secrets), campaigns (goal, dates, department, budget), content items (title, body or caption per channel variant, media from Documents, author: human or agent), status (idea, draft, in review, approved, scheduled, published, failed, archived), a content calendar (scheduled time per channel), approvals (publishing is an external send, so agent-authored posts go through the approval queue), published references (platform post id and URL), performance snapshots pulled from the platforms (impressions, engagement, clicks), and links to contacts or deals for attributed leads.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| SM1 | What's going out this week, on which channels (the content calendar)? | R | SA, DA, U |
| SM2 | What's in draft or waiting for review, and who's it waiting on? | R | DA, U, Ag |
| SM3 | Which posts did agents draft, and which are approved to publish? | R | DA |
| SM4 | Which scheduled posts failed to publish, and why? | R | DA, Ag |
| SM5 | What have we published for campaign X, and how is it performing? | R | SA, DA |
| SM6 | Which posts performed best this month, by channel? | R | SA, DA, Ag |
| SM7 | Are there gaps in the calendar (channels with nothing scheduled in the next N days)? | R | DA, Ag |
| SM8 | Which leads or deals came from content (campaign or post attribution)? | R | SA, DA |
| SM9 | Which channels are connected, and is any connection expired or broken? | R | SA, DA |
| SM10 | Have we already posted about topic X, and when? | R | U, Ag |
| SM11 | What did the campaign cost (spend plus hours plus AI spend) against its results? | R | SA |
| SM12 | Who edited, approved and published this post, and what changed between draft and published? | A | SA, DA |
| SM13 | Was anything published to a channel without an approval? *(must return none; this is the audit check)* | R+A | SA |

## 18. Tenant, sovereignty & cross-cutting audit

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| X1 | What happened to record X, in order (full history of any record)? | A | SA, DA |
| X2 | What did member X (human or agent) do between two dates? | A | SA, DA (own: all) |
| X3 | What did the AI change today, through the assistant bar, MCP or agents? | A | SA, DA |
| X4 | Who deleted something this week, and what was it? | A | SA |
| X5 | When was our last export, and who ran it? | A | SA |
| X6 | When was the last nightly backup, and did the restore rehearsal pass? | R | SA |
| X7 | Which MCP clients (Claude Desktop, Claude Code, our agents) are connected, and what do they call most? | R+A | SA |
| X8 | What did I work on last week in the app? | A | all |

## 19. Bookkeeping & the general ledger (module `books`)

Implies: a chart of accounts (code, name, type, parent, bank flag), fiscal periods with an open/closed/locked status, journal entries (date, period, memo, source and the document behind it, status, reversal link) with their lines (account, debit or credit, department, customer, project), posting rules that map invoices, payments, expenses, AI usage, payroll and stock to accounts, bank accounts, imported bank transactions with their match state, and reconciliations.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| GL1 | What is our profit and loss for a period, by account? | R | SA, DA, Ex |
| GL2 | What is the balance sheet as of a date? | R | SA, Ex |
| GL3 | What is the trial balance for a period, and does it balance? | R | SA, Ex |
| GL4 | What is the balance and activity on account X for a period? | R | SA, Ex |
| GL5 | Which journal entries are still in draft, and which period do they fall in? | R | SA, Ex |
| GL6 | What did this invoice / payment / expense post to the books? | R | SA, Ex |
| GL7 | Which bank transactions are still unmatched, and by how much do we differ from the statement? | R | SA, Ex |
| GL8 | Is the bank reconciled for a period, and who completed it? | R+A | SA, Ex |
| GL9 | Which posting rule sends a category or document type to which accounts? | R | SA, Ex |
| GL10 | Which periods are closed or locked, and who closed them? | R+A | SA, Ex |
| GL11 | What did we owe and what were we owed at period end (payables and receivables against the ledger)? | R | SA, Ex |
| GL12 | What was reversed or voided in the books, and why? | R+A | SA, Ex |
| GL13 | Did anyone change a posted entry or post into a closed period? *(must return none; this is the audit check)* | R+A | SA |
| GL14 | Does the AI usage posted for a period agree with the prompt ledger and with the journal? | R | SA, Ex |

## 20. Shared inbox (module `inbox`)

Implies: mailboxes (address, shared or personal, department, inbound method and its credential reference, auto-ticket rules), threads (subject, customer and contact, linked ticket or deal, assignee, status, counts, last message), messages (direction, addresses, body, sent/received, the MaluMail delivery record for outbound), attachments that can be filed into Documents, per-member read state, and routing rules.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| IB1 | What is unanswered in the shared inbox right now, and how old is the oldest? | R | SA, DA, U |
| IB2 | What is assigned to me, and what have I not read? | R | U, Ag |
| IB3 | What has this customer written to us, across every mailbox? | R | all insiders |
| IB4 | Which threads have no assignee? | R | DA |
| IB5 | Find the email where someone said X (full-text). | R | insiders |
| IB6 | Which threads became tickets or deals, and which did not? | R | DA |
| IB7 | How long do we take to first reply, by mailbox and by person? | R+A | SA, DA |
| IB8 | What did we send out from the shared inbox, and did it deliver? | R | DA |
| IB9 | Which attachments arrived and which were filed into Documents? | R | U |
| IB10 | Which routing rules are active on a mailbox, and what do they do? | R | DA |
| IB11 | Who replied to this thread, edited a rule, or reassigned it? | A | SA, DA |

## 21. People & payroll (module `people`)

Implies: employment profiles for humans (type, title, department, manager, start and end dates, status, pay type, rate, schedule, contracted hours, payment details as a secret reference), compensation history, pay runs (period, pay date, status, totals, the journal entry they posted) with per-person items and their earning/deduction lines, leave types, per-year balances, and leave requests with their decisions. Statutory tax calculation and filing are out of scope; the pay run records what was decided and paid.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| PE1 | Who works here as an employee or contractor, in which department, reporting to whom? | R | SA, DA |
| PE2 | What are my employment details and my current pay? | R | U |
| PE3 | What does person X cost us per month, including employer costs? | R | SA |
| PE4 | What is our total payroll for a period, by department? | R | SA, Ex |
| PE5 | How has someone's pay changed over time, and who approved each change? | R+A | SA |
| PE6 | What is in this pay run, per person, and what did it post to the books? | R | SA, Ex |
| PE7 | Which pay runs are still unapproved or unpaid? | R | SA |
| PE8 | How much leave do I have left this year? | R | U |
| PE9 | What leave is waiting for my approval? | R | DA |
| PE10 | Who is off next week, and does it clash with scheduled work? | R | DA |
| PE11 | Who is due to start or has just left, and is their onboarding or offboarding complete? | R+A | SA, DA |
| PE12 | What do we pay people versus what we bill for their time? | R | SA |
| PE13 | Who viewed or changed an employment or pay record? | A | SA |

## 22. Products & inventory (module `inventory`)

Implies: a product master (SKU, kind, unit, cost and sale price, tax, stock tracking, reorder point, supplier, ledger accounts), stock locations (warehouse, shop, vehicle — physical places, distinct from the estate's offices and desks), levels per product and location, movements with their source document, and purchase orders with lines and receipts.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| IV1 | What do we sell, at what price, and what does it cost us? | R | SA, DA, U |
| IV2 | How much of product X do we have, and where? | R | insiders |
| IV3 | What is below its reorder point and should be ordered? | R | SA, DA |
| IV4 | What did we sell of each product this period, and at what margin? | R | SA, DA |
| IV5 | What moved in or out of stock, when, and against which document? | R | DA |
| IV6 | What is the value of stock on hand, by location? | R | SA, Ex |
| IV7 | Which invoices or quotes include product X? | R | DA, U |
| IV8 | What purchase orders are open, and when are they expected? | R | DA |
| IV9 | What did we receive against a purchase order, and what is still outstanding? | R | DA |
| IV10 | Which supplier do we buy X from, and what do they charge? | R | DA |
| IV11 | Where does the last stock count differ from the system, and by how much? | R | SA, DA |
| IV12 | Who adjusted or wrote off stock, and why? | A | SA, DA |

## 23. E-signature (module `signatures`)

Implies: signature providers (adapter, credential reference, default), signature requests (the document, what it belongs to, signing order, status, expiry, the executed copy), signers (our side or the customer's, order, status, viewed and signed times), and an append-only event trail.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| SG1 | What is out for signature right now, and who are we waiting on? | R | SA, DA, U |
| SG2 | What is the status of the signature request on quote / contract X? | R | insiders |
| SG3 | Which requests expire in the next N days, or have already expired? | R | DA |
| SG4 | Who signed what, when, and from where (the audit trail)? | R | SA, Ex |
| SG5 | What was declined, and for what reason? | R | SA, DA |
| SG6 | Where is the executed copy of the signed document? | R | insiders |
| SG7 | How long do customers take to sign, on average? | R | SA |
| SG8 | Who sent, resent, voided or cancelled a signature request? | A | SA, DA |

## 24. Customer portal & forms (module `portal`)

Implies: forms (slug, kind, status, whether a login is needed, what a submission becomes, target department/pipeline/category, notifications, success behaviour) with their fields and mapping to record columns, submissions (data, source, status, the records they created), and the portal's own settings — which sections an External member sees and whether they may open tickets or pay online.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| PF1 | Which forms are published, and where does each one send its submissions? | R | SA, DA |
| PF2 | What came in through the forms this week, and what is still unprocessed? | R | SA, DA, U |
| PF3 | What did this submission say, and which contact, ticket or deal did it create? | R | insiders |
| PF4 | Which form produces the most leads, and how many convert? | R | SA |
| PF5 | What is turned on in the portal, and can customers open tickets or pay there? | R | SA, DA |
| PF6 | Which customers have portal access, and when did they last sign in? | R+A | SA, DA |
| PF7 | What can customer X see in the portal right now? | R | SA, DA |
| PF8 | Which submissions were marked spam or rejected, and by whom? | R+A | DA |
| PF9 | What did a customer do in the portal — viewed an invoice, paid, opened a ticket? | A | SA, DA |
| PF10 | Who published, changed or closed a form? | A | SA |

## 25. Reporting & dashboards (module `reports`)

Implies: report definitions (a named MCP tool plus fixed and prompted parameters, the module that gates it, how it is drawn, shared or private), runs with their parameters and outcome, schedules with recipients and format, and dashboards with their widgets.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| RP1 | Which saved reports exist, and which can I run? | R | insiders |
| RP2 | Run report X for this period and show me the result. | R | insiders |
| RP3 | Which reports are scheduled, to whom, and when do they next go out? | R | SA, DA |
| RP4 | Did the scheduled report go out, and did anything fail? | R | SA |
| RP5 | Which reports does nobody run any more? | R | SA |
| RP6 | What is on my dashboard, and what does each tile answer? | R | insiders |
| RP7 | Which dashboards are shared with my department? | R | insiders |
| RP8 | Export report X for the accountant. | R | SA, Ex |
| RP9 | Who created, changed or scheduled a report? | A | SA |

## 26. Company profile (no module — every insider reads it; approved 2026-09-20)

Implies: a singleton profile beside the business settings (tagline, about, mission, facts, social links, logo and hero image, published or not), a curated list of offerings — catalog items, inventory products or free-form showcase cards, each with its own words, picture, price display and order — and one versioned JSON document served to a bearer token once published: the source a display website is built from. Identity (name, address, email, phone, website) stays in business settings; `tax_id` is never part of it.

| # | Question | Mem | Asked by |
| --- | --- | --- | --- |
| CP1 | What does our company do, and how do we describe ourselves? | R | insiders |
| CP2 | What products and services do we present to the outside world, and at what price? | R | insiders |
| CP3 | What are our public contact details — address, email, phone, website, social links? | R | insiders |
| CP4 | Is the company profile published, and what would a website built from it contain? | R | insiders |
| CP5 | Who changed or published the company profile, and when? | A | SA |

## Questions the design deliberately won't answer

- **Users:** anything outside their grants, e.g. "What's X's salary or hourly rate?", "What's in the Finance department's private documents?". The answer comes back empty, as if the record doesn't exist, never as "you're not allowed".
- **External users:** anything not explicitly shared with them, including other customers' records and the existence of internal notes on their own tickets.
- **Agents:** nothing beyond their member row's visibility. An agent cannot read other agents' prompt payloads, provider API keys or MCP token secrets, even with Owner-level visibility granted to its manager.
- **Anyone, through MCP:** provider credentials, token hashes, password or 2FA secrets, and the raw content of a desk's local files (desk content reaches the server only through a confirmed import).
- **Desk contents to other members:** "What files are on Robert's desk?" is never answerable. A brokered, consented task can return a *result*; nothing browses a desk.

## Review decisions (2026-09-17)

1. **Invoicing scope:** both documents/status and online payment collection in v1. Applied as S15–S22 and the payment implications in §3.
2. **Chart of accounts:** flat expense categories plus an accountant export (E13) — *superseded 2026-09-17*: a full double-entry ledger is in v1 (§19), and the expense categories now map to accounts through posting rules.
3. **Document search:** PostgreSQL full-text search in v1; MaluDB semantic indexing is a Phase 4 enhancement.
4. **AI spend on projects:** counts toward project cost; prompt-ledger entries carry the task/project link (P8, P13, E7, SM11).
5. **Cert-study modules:** stay functional underneath with no new questions; retiring them is a separate decision.
6. **Content & social module:** in v1. Applied as §17.

## Open points for the next review

1. ~~**First payment provider**~~ — **decided 2026-09-18: Stripe.** Payment links plus webhooks cover S15–S22 with no PCI scope beyond SAQ-A, because card data never touches this server. The provider stays behind the adapter `db/038` was designed around, so a second provider is a new adapter rather than a new schema. Three follow-on decisions taken the same day, for `docs/build-specs/sales-online-payments.md`:
   - **Secrets:** the slice builds the first `tenant_secrets` writer — AES-256-GCM in PHP with a new `SECRETS_KEY` in `config/.env`, keeping `key_version` and `last4` for rotation and display. This matches the existing `APP_TOTP_KEY` / `ACTION_TOKEN_KEY` pattern and honours the estate rule that an application endpoint carries only a *reference* to a tenant secret, never the secret.
   - **Webhooks:** built properly — raw-body signature verification, every event stored in `provider_events` with `signature_verified`, processing idempotent on `provider_event_id` — and acceptance-tested through `stripe listen --forward-to`, which needs no inbound access. **Deployment prerequisite, recorded rather than assumed:** this server has no TLS, no public hostname and answers on HTTP port 80, so Stripe cannot deliver to it as configured. Going live needs the domain and certificate; no code changes.
   - **Order:** the ledger is built first (it closes M3), so Stripe fees and payouts have accounts to post to instead of being recorded and left dangling.
2. **Social publishing depth:** plan-and-approve only (someone posts by hand and pastes the link), or direct publishing through platform APIs with metrics pull? Recommendation: planning, approval and calendar in the Phase 3 slice; direct publishing and metrics connectors in Phase 4, one platform at a time, since each platform's API review takes time outside our control.
3. **Which platforms first** (if direct publishing): LinkedIn, Facebook/Instagram, X, a newsletter tool? This should follow the first target customer (still an open requirements question).
