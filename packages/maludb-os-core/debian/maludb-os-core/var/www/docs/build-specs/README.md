# Slice build specs — index

> **Business OS specs** (the conversion) live beside these:
> `business-os-slice-template.md` (the worker template), `contacts-crm.md` (the exemplar,
> **built**), `sales-invoicing.md` (phase 2, slice 1 — **core built**; online collection waits
> the online-collection slice, now unblocked — the provider is Stripe), `expenses.md` (phase 2, slice 2 — **built**),
> `bookkeeping-ledger.md` (phase 2, slice 3 — **built**, M3 closed), `estate.md` (pulled
> forward from phase 4 — **built**), `agent-hr.md` (pulled forward from phase 5 — **built**,
> with the prompt library and orchestrator rosters), `applications.md` (the technical asset
> registry — ready for a worker; it is what makes new agent capability possible).
> The cert-study specs below describe the fork's own modules, which keep running untouched.

One spec per Phase 3 vertical slice (plan §5). The **exemplar** (`exam-catalog`) is built first by the planning-class model and becomes the canonical reference; every later spec is phrased as *"build exactly like the exam-catalog slice, applying this spec."* A worker makes **substitutions, never decisions** — ambiguity → stop, record under Open Questions, escalate.

Build order and status:

| # | Slice | Spec | Tables | Notes |
|---|---|---|---|---|
| 1 | Exam Catalog (organizer) | ✅ `exam-catalog.md` | exams, exam_domains, community_settings | **exemplar** + seed — **BUILT & verified** |
| 2 | Exam Attempts + Calendar (exam layer) | ✅ `exam-attempts.md` | exam_attempts | calendar month grid → agenda on mobile |
| 3 | Community Events + RSVPs | ✅ `community-events.md` | community_events, event_rsvps | event layer on calendar |
| 4 | Resources + endorsements | ✅ `resources.md` | resources, resource_exams, resource_domains, resource_endorsements | before plans (items link resources) |
| 5 | Study Plans + items + comments + copy | ✅ `study-plans.md` | study_plans, plan_items, plan_comments | copy shifts due dates |
| 6 | Study Log | ✅ `study-log.md` | study_sessions | quick-add row; weekly totals by domain |
| 7 | Issues + Replies (+ FTS) | ✅ `issues.md` | study_issues, replies | accept answer; reply notifications |
| 8 | Members directory + profiles | ✅ `members.md` | members (read) | composed from visible attempts/plans/issues |
| 9 | Dashboard | ✅ `dashboard.md` | (composes all above) | no new tables |
| 10 | Organizer: Community Health | ✅ `community-health.md` | (read aggregates) | at-risk, pass rate, expiring, trend, unanswered |
| 11 | Scheduled jobs (cron) | ✅ `scheduled-jobs.md` | notifications, *_tokens | reminders, invite expiry, calendar feed |

All specs written. Slices 2–11 replicate the **exam-catalog** exemplar and its "Canonical patterns" section; where a slice diverges from plain CRUD (calendar grid, study-log quick-add, dashboard composition, health dashboards, cron jobs), the spec says so and specifies its own structure. Each spec's Open Questions is empty — a worker builds it making substitutions, not decisions, and escalates (never improvises) if anything is ambiguous.

Each spec follows the template in the plugin's `new-app/references/slice-build-spec.md`: Screens · List screen · Form · Files · Query functions · Action-manifest entries · Activity-log events · Status vocabulary · Out of scope · Open Questions.
