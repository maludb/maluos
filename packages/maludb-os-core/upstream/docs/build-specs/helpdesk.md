# Build spec: Helpdesk — "what has a customer or teammate asked us to fix?"

2026-09-19 · Module 5 of the stubbed modules (`docs/build-specs/stub-modules-decisions.md`).
Schema: db/034 (`tickets`, `ticket_messages`, `ticket_categories`, `sla_policies`; views
`mcp_tickets`, `mcp_ticket_messages`) + additive **db/109**. Manifest "Tickets": 6 internal
screens + 3 portal screens, 13 internal actions + 2 portal actions. Tools: `find_tickets`,
`get_ticket`, `sla_status`, `similar_tickets`, `ticket_metrics`.

## db/109 (additive)
- **`business_hours`** (owner's decision 8): one row per weekday (1 = Monday … 7 = Sunday),
  `opens` / `closes` (time, in the business timezone), `is_open`; seeded Mon–Fri 09:00–17:00;
  read view `mcp_business_hours` (insider). Edited on Settings → Business by a super-admin
  (new action `business_hours_save`, added to the manifest). No holidays yet.
- Read views for the two lookup tables that had none: `mcp_sla_policies`,
  `mcp_ticket_categories` (insider-open, archived rows left out).

## The SLA clock
A ticket takes the SLA policy of its priority (its department's policy if one exists, else the
business-wide one). `first_response_due_at` and `resolution_due_at` are computed when the ticket
is created and **recomputed when its priority changes** (from the ticket's creation, as the
manifest's undo implies). With `business_hours_only` the minutes are counted only inside
business hours, in the business timezone: a ticket opened Friday 16:30 with a 60-minute target is
due Monday 09:30. If no weekday is open at all the clock falls back to 24 / 7 rather than never
being due. While a ticket is `pending` (waiting on the customer) or `on_hold` the due times are
shown but not counted as breached; pausing the clock itself is recorded OPEN.
`first_responded_at` is set by the first PUBLIC reply from someone who works here.

## Status walk
`new` → `open` (first staff reply, or an assignment) → `pending` | `on_hold` ↔ `open` →
`resolved` (with an optional summary; `resolved_at`, `resolved_by`) → `closed`. `ticket_reopen`
(staff, or the requester of their own ticket) returns a resolved or closed ticket to `open` and
counts it (`reopened_count`). A customer's reply to a resolved ticket reopens it.

## Who may do what
Reading is the view's decision — the list and the ticket page are open to any insider and show
what `mcp_tickets` shows them (so an assignee without the grant reads their ticket, read-only).
`mcp_tickets` admits the requester to their own ticket, and everyone else through
`app_can_see('tickets', assignee, department, …)`. `mcp_ticket_messages` never shows an External
caller an internal note. Staff actions need `mod:tickets`; delete is admin. **An agent's public
reply needs a person's approval** (policy `ticket.reply`, seeded in db/053 — confirmed as the
default in the decisions file).

## Mail
`ticket_reply` emails the requester (their contact's or member's address) through MaluMail with
a new template pair `emails/ticket-reply.{html,text}.php`: the reply, the ticket number and
subject, and — for a requester who has portal access — nothing else; there is no Reply-To, so a
customer answers in the portal, and mail-in arrives with the Inbox module. A requester with no
address gets no mail and the action says so.

## Screens
`/tickets` (filters: status, mine, department, priority, organization, unreplied, sla =
breached / due soon), `/tickets/new`, `/tickets/{id}` (the thread, reply / internal note,
assign, priority, status, resolve, reopen, close, time logged against it), `/tickets/{id}/edit`,
`/settings/sla`, `/settings/ticket-categories`. The three **portal** screens' PHP
(`html/portal/requests/…`, External callers, own tickets only) is built here; their React pages
are built with the `/portal` layout in the Portal & Forms module.

## Actions
As the manifest lists them, handlers in `html/tickets/`, `html/settings/sla/`,
`html/settings/ticket-categories/`, `html/portal/requests/`. `ticket_update` is a partial update.
