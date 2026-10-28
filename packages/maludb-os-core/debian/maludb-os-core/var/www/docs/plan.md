# MaluDB OS — Plan

Status: **COMPLETE — Phases 0–4 all done. The full application is built, verified, and live at members.aimasters.vip.** · Started 2026-09-13 · Updated 2026-09-15

**Phase 4 step 5 — Settings screen DONE & live (Phase 4 complete):** section nav (profile / notifications / security / AI access / calendar feed). Profile + notification-preference editing; full **TOTP 2FA enrollment** (QR via endroid/qr-code, confirm, 10 recovery codes) + disable; **MCP access token** create/revoke with the published `/mcp/records` + `/mcp/activity` endpoints (SaaS Plus+); **iCal calendar feed** create/rotate/revoke. Verified through Apache: profile save, a Settings-minted MCP token works against the live records server, calendar feed returns text/calendar, and 2FA enroll→enable→(login now routes to /login/2fa)→disable.

**Phase 4 step 3 — unified assistant DONE & live:** `assistant_service.py` (systemd, localhost:8765) — one Claude Agent behind both the command bar and the AMA page; connects to all three MCP servers with the caller's action token (read servers now also accept it via db/015 `mcp_member_role`), runs the Anthropic tool-use loop, returns answer + navigate/refresh directives, keeps per-session history. `/assistant/message.php` (command bar, every screen) and `/ask` (AMA chat page) mint the token, call the service, and emit `HX-Location`/`HX-Trigger`. Verified end-to-end through Apache/PHP: record question ("next exam → 9 days"), navigation (`HX-Location /plans/`), action ("logged 25 min" + `HX-Trigger sessionsChanged` + DB write, source=assistant), AMA (listed CCAO-F domains). Model `ASSISTANT_MODEL` (default claude-sonnet-5); key in `config/.env`. Four systemd units: maludb-os-{records,activity,actions}-mcp + maludb-os-assistant.

**Phase 4 step 2 — actions MCP server DONE & live:** PHP action-token infra (`mint_action_token`/`verify_action_token`, HMAC 10-min TTL; bootstrap accepts `X-Action-Token` and acts as that member; `verify_csrf` skips for action-authed; `emit_action_status` header helper). `maludb_os_actions_mcp` (systemd, localhost:8813, **not** Apache-proxied): `navigate` → HX-Location directive; `log_study_time`/`post_issue`/`rsvp_event`/`record_exam_result` resolve entities via the read views and POST to the app's own endpoints with the token. Verified end-to-end: resolution, DB writes, `source=assistant` activity, 401 on bad token, 404 via Apache. ANTHROPIC_API_KEY now present → step 3 can run.

**Phase 4 step 1 — read MCP servers DONE & live:** `maludb_os_records_mcp` (25 tools over the `mcp_*` views) + `maludb_os_activity_mcp` (8 tools over `mcp_activity_*`), Python + FastMCP (mcp 1.x) + asyncpg in `/var/www/mcp` (venv gitignored). Bearer-token auth via the `mcp_resolve_token` SECURITY DEFINER fn (db/014); every tool RLS-scoped to the token's member; guarded `records_search`/`activity_search` (single SELECT, 5s timeout, 200-row cap) safe by construction. Read roles `app_records_ro`/`app_activity_ro` see only the views. Deployed as systemd services (localhost 8811/8812, auto-restart/boot); Apache reverse-proxies `/mcp/records` + `/mcp/activity` (ProxyPreserveHost **Off**). Verified end-to-end incl. through the proxy: real data, RLS scoping by role (members get nothing from organizer-only tools/search), 401 on bad token, writes rejected. `bin/mint_mcp_token.php` mints per-member tokens; deploy artifacts in `docs/deploy/`. **Remaining Phase 4:** actions MCP server, unified Claude Agent SDK assistant (needs ANTHROPIC_API_KEY), settings token UI.

**Deployed & running:** `maludb_os` database on the local PostgreSQL 17 cluster (:5432), served by Apache at `/var/www/html` (https://members.aimasters.vip). `app_rw` role + `config/.env` (perms 640 maludb:www-data). Errors log-only unless `APP_DEBUG=1`. Composer libs in `/var/www/vendor`.

**All 11 slice build specs written** (`docs/build-specs/`) — slices 2–11 replicate the exemplar's canonical patterns; each Open Questions is empty, ready for worker-class builds.

**Phase 3 slice 11 — Scheduled jobs + iCal feed done & verified live → PHASE 3 COMPLETE.** Five idempotent cron jobs (exam reminders 7d/1d, cert-expiry 30/14/7d, event reminders ~24h, invite-expiry report, notification email flush) writing dedup'd in-app notifications + MaluMail on opt-in; `notify_once` prevents double-sends (verified re-run creates 0). Public token-authenticated iCal feed at `/feed/calendar.php?token=` (verified valid VCALENDAR, bad token → 404, fetch logged). `docs/deploy/crontab.example` for install. `docs/build-specs/scheduled-jobs.md`.

**Phase 3 slice 10 — Organizer: Community Health done & verified live:** organizer-only read dashboards, panels lazy-loaded via Pattern-A fragments — at-risk members (no plan / stale study), pass rate (shared-only anonymous, verified 50% · 1/2), expiring certifications (60d), unanswered issues, weekly activity trend, pending-invitations teaser. Query logic mirrors the `mcp_*` organizer views. RBAC verified (members 403 on page + fragments). `docs/build-specs/community-health.md`.

**Phase 3 slice 9 — Dashboard done & verified live:** live tiles (days-to-next-exam, this-week's plan items, month study minutes, replies waiting), cert-expiry banner, this-week plan items with inline complete, upcoming calendar (exams ∪ events, 30 days), unread notifications with mark-read / mark-all. Composition slice (no new tables); tile ids preserved. Conformance passed; activity logged (`notification.read`, `plan_item.complete`). `docs/build-specs/dashboard.md`.

**Phase 3 slice 8 — Members directory + profiles done & verified live:** read-only directory (search by name, filter taking/certified-in an exam, sort) showing each member's shared certifications + visible upcoming exams; profile composes certifications, visible exams (results masked unless shared — verified an unshared fail does NOT leak), community plans, issues + accepted answers, hosted events. Conformance passed (read-only, no write endpoints). `docs/build-specs/members.md`.

**Phase 3 slice 7 — Issues + Replies done & verified live:** post/edit issues, threaded replies, **accept-answer** (resolves + notifies replier), resolve toggle, organizer hide (issue + reply), **Postgres FTS** with relevance sort + unanswered filter (fixed: NOT EXISTS in WHERE, not HAVING), and **in-app notifications** on reply (`issue_reply`) and accept (`reply_accepted`). Author-only edit/resolve/accept; verified non-author accept → 403. Conformance passed; activity logged (`issue.*`, `reply.*`). `docs/build-specs/issues.md`.

**Phase 3 slice 6 — Study Log done & verified live:** quick-add card (minutes/domain/confidence/exam/date/note/resource) that fires `sessionsChanged` to refresh the recent-list and by-domain totals regions; monthly totals-by-domain with confidence-colored bars + month selector (M4/M10); edit + delete (owner-scoped). Conformance passed; activity logged (`session.log/update/delete`). `docs/build-specs/study-log.md`.

**Phase 3 slice 5 — Study Plans + items + comments + copy done & verified live:** plan list (scope/exam/status/sort filters), create/edit with the inline items editor (add/edit/complete/delete via `hx-include="closest tr"`), detail with progress + read-only items, copy-to-my-attempt (shifts item due dates, verified), comments on community plans (notifies owner), visibility/archive toggles. Owner-scoped mutations; private plans 404 to non-owners (verified). Conformance passed; activity logged (`plan.*`, `plan_item.*`, `plan_comment.create`). `docs/build-specs/study-plans.md`. NOTE: never `sed -i` config/.env — it drops the www-data group; re-chown maludb:www-data 640 after any edit.

**Phase 3 slice 4 — Resources + endorsements done & verified live:** submit/edit/view resources with exam+domain coverage (multi-select), endorse toggle (list row + detail), organizer hide/unhide, Postgres full-text search, and ranking by certified-member endorsements (verified: a shared pass lifts `certified_endorsement_count`). Conformance passed; activity logged (`resource.*`). `docs/build-specs/resources.md`.

**Phase 3 slice 3 — Community Events + RSVPs done & verified live:** events list/detail/create/edit, RSVP (going/maybe/not-going) with attendee list, duplicate-to-new-date, cancel (notifies attendees), host/organizer authz. Events layered onto the calendar with a layer toggle (exams/events/all). Timezone-correct: events stored UTC, entered/rendered in the viewer's tz (verified CDT→UTC). Added tz helpers (`format_ts`/`local_to_utc`) + `SET TIME ZONE 'UTC'` per connection. Conformance passed; activity logged (`event.*`, `rsvp.set`). `docs/build-specs/community-events.md`.

**Phase 3 slice 2 — Exam Attempts + Calendar done & verified live:** owner-scoped attempts CRUD (create/edit/delete, status, record-result→auto cert dates, share toggle, calendar-visibility, start-renewal) + server-rendered month calendar (grid desktop / agenda mobile, prev-next, exam filter, `HX-Target: calendar-region` refresh). Conformance passed; activity logged (`attempt.*`). Reschedule detected via before/after date. `docs/build-specs/exam-attempts.md`.

**Phase 3 slice 1 — Exam Catalog (exemplar) done & verified live:** organizer list (search + server pagination) · exam add/edit/delete · inline domains editor (add/edit/delete/reorder, live weight-sum badge) · retake-policy panel. Conformance checklist passed; activity logged (`exam.*`, `domain.*`, `settings.update`). Canonical patterns for worker slices recorded in `docs/build-specs/exam-catalog.md` (HX-Target dual endpoint, write→refreshed-list-into-#page-content, `hx-include="closest tr"` child rows, form.php URLs pending mod_rewrite).

**Phase 2 built & verified** against an isolated PostgreSQL 17 cluster: infra (`app/` bootstrap/db/http/auth/totp/activity/mail with the RLS request context) · invite-only auth (register, login with per-account+per-IP throttle & timing equalization, logout, password reset via MaluMail, Google OIDC, TOTP 2FA + recovery codes) · design-system `nxl` app shell + dashboard + assistant command bar + activity logging · organizer Invitations screen + `bin/bootstrap_organizer.php`. End-to-end smoke test passed: unauthed→login redirect, login, invite→register→auto-login, organizer RBAC (403 for members), HTMX partials, and a full mobile-first structural audit (no `.modal`, `.table-responsive`, full-width command bar, viewport meta). Composer libs (otphp, endroid/qr-code, league/oauth2-google) in `/var/www/vendor`. Secrets via `/var/www/config/.env` (see `.env.example`).

**Phase 1 deliverables (for review):** full schema in `db/000`–`db/020` (validated against a throwaway PostgreSQL 17 cluster — all 15 files apply clean, RLS masking + read-role isolation verified) · MCP tool surface `docs/mcp-tool-surface.md` (every M/O question mapped to a tool) · action manifest `docs/action-manifest.md` · exemplar build spec `docs/build-specs/exam-catalog.md` + index (remaining 10 slice specs generated after schema sign-off).
Stack: PostgreSQL 17 (record memory) + MaluDB (activity memory) · Apache / PHP / Bootstrap 5.3 / HTMX · Python FastMCP servers + Claude Agent SDK assistant

A community app where members plan, track, and get help studying for the four Anthropic Claude Partner Network certification exams. Following the memory-first method: **who asks → what they ask → what must be remembered**. Features are the questions people ask most often.

---

## 0. Decisions log

| # | Decision | Effect on the design |
|---|---|---|
| D1 | **One community** | One dedicated PostgreSQL + MaluDB and one set of MCP endpoints. No community/tenant table, just a singleton `community_settings`. |
| D2 | **All 4 Anthropic partner exams** | Exam catalog seeded with CCAO-F, CCDV-F, CCAR-F, CCAR-P and their domains (§3.3) |
| D3 | **Results are pass/fail only** | No score is stored. Sharing a result is opt-in, private by default (the recommendation, not objected to). |
| D4 | **Study log in v1** | Study Session is a core entity |
| D5 | **Invite-only** | Invitation entity. Registration and Google sign-in both require a valid invite for that email. |
| D6 | **Plans can be private** | Visibility on plans, enforced by row-level security everywhere, the MCP servers included |
| D7 | **Calendar shows exam dates and community events** | Community Event + RSVP entities. The calendar combines both. |
| D8 | **Keep copy-a-plan and the Resources library** | `copied_from_plan`, Resource, and Resource Endorsement entities |

---

## 1. Actors — who asks?

| Actor | Who they are |
|---|---|
| **Member** | An invited community member preparing for one or more exams (or already certified and helping others) |
| **Organizer** | Runs the community: invites members, maintains the exam catalog, hosts and moderates events, moderates posts, watches community health |
| **Assistant** | The AMA agent / command bar, acting as the signed-in member or organizer |
| **Member's own AI** | A member's Claude Desktop / Claude Code connected to the community MCP endpoints with their personal token |

"Certified member" is not a role. The app works it out from passed, unexpired attempts.

---

## 2. Question inventory — what do they ask?

R = record question (PostgreSQL) · A = activity question (MaluDB logs)

### Member
| # | Question | Mem |
|---|---|---|
| M1 | When is my exam, and how many days do I have left? | R |
| M2 | Who else is taking the same exam around the same time as me? *(study buddies)* | R |
| M3 | What's on my study plan this week, and am I on track? | R |
| M4 | Which domains am I weakest in? *(study-log confidence + time vs. domain weight)* | R |
| M5 | Has anyone else been stuck on what I'm stuck on, and how did they get past it? | R |
| M6 | Who has passed this exam and could help me with domain X? | R |
| M7 | What did people who passed use as their study plan? | R |
| M8 | Did anyone reply to my issue or comment on my plan? | R |
| M9 | What's on the community calendar this week (exams and events)? | R |
| M10 | How much have I studied this month, and on what? | R |
| M11 | What study groups or workshops are coming up for my exam? | R |
| M12 | Who's coming to Thursday's study group? | R |
| M13 | What are the best resources for domain X, according to people who passed? | R |
| M14 | When does my certification expire, and when should I renew? | R |
| M15 | If I didn't pass, when am I allowed to retake? *(from attempt history + retake policy)* | R |
| M16 | When did I start studying for this exam? | A |
| M17 | How many times have I rescheduled my exam? | A |
| M18 | What did I work on last week in the app? | A |
| M19 | What changed in the community since I last logged in? | A |

### Organizer
| # | Question | Mem |
|---|---|---|
| O1 | Who is taking which exam this month? | R |
| O2 | Who has an exam coming up but no plan, or hasn't logged study in 2+ weeks? *(at-risk)* | R |
| O3 | What are the most common issues per exam domain? *(what workshops to run)* | R |
| O4 | What's our community pass rate per exam? *(shared results only)* | R |
| O5 | Which issues have no replies? | R |
| O6 | Who helps others the most (accepted answers, endorsed resources, events hosted)? | R |
| O7 | Which plans get copied most? | R |
| O8 | Who's been invited but hasn't joined? | R |
| O9 | Whose certifications expire in the next 60 days? | R |
| O10 | Which kinds of events draw the most RSVPs? | R |
| O11 | Which resources show up most in passers' plans? | R |
| O12 | How active is the community week over week? | A |
| O13 | How long do passers typically take from first plan to exam day? | R+A |
| O14 | Who invited this member, and when did they first log in? | R+A |
| O15 | Who hid, edited, or cancelled this post or event, and when? *(moderation audit)* | A |

### Questions the design deliberately won't answer for members
- "Who viewed my issue, plan, or profile?" View events are logged, but only organizers can see them in aggregate.
- "Did so-and-so pass?" Only if that member chose to share the result.
- "What's in so-and-so's private plan?" Never, including through the assistant or MCP (RLS, §6).

---

## 3. Memory model — what must be remembered?

Written in domain language. The SQL comes in Phase 1.

### 3.1 Record memory (PostgreSQL)

**Member** — an invited person: display name, email, timezone, short bio, organization (optional), role (`member` / `organizer`), notification preferences, joined date. Auth structures (Google identity, TOTP, recovery codes) follow the standard php-session-auth schema.

**Invitation** — permission for an email address to join: email, role granted, invited by, personal message, token (hashed), expires at, accepted at + resulting Member, revoked at. Sent through MaluMail. Registration (password or Google) succeeds only against a valid, unexpired, unrevoked invitation for that email.

**Exam** — a certification in the catalog: code, name, audience, description, official guide URL, duration (min), question count, passing score (720/1000, for information only), validity months (12), guide version, active flag. Maintained by organizers.

**Exam Domain** — a weighted topic area within an Exam: name, weight %, sort order. Plan items, issues, study sessions, events, and resources are all tagged by domain.

**Exam Attempt** — a Member's intent to sit an Exam, from first idea to result. A retake is a new attempt, and so is a renewal.
- kind: `exam` (proctored, Pearson VUE) / `renewal` (free, non-proctored on-time renewal)
- status: `considering` → `scheduled` → `taken` → `passed` / `not_passed` · or `withdrawn`
- exam date (required once scheduled), start time (optional, member's timezone), delivery (`online` / `test_center`), `date_is_tentative` flag
- `calendar_visible` (default true — see §8) · `result_shared` (default false)
- on pass: `certified_on`, `certified_until` (= certified_on + the exam's validity months, fixed when the result is recorded)
- The calendar is a view over attempts. Reschedules edit the date in place, and the before/after dates go to the activity log (M17). No reschedule table.

**Study Plan** — a Member's plan for an Exam Attempt: title, approach (markdown), visibility (`community` / `private`), status (active / archived), `copied_from_plan` (O7). Copying a plan copies its items with the due dates shifted to the new exam date.

**Plan Item** — one milestone: title, domain, due date, notes, optional Resource, completed date. "On track" (M3) = items completed vs. items due by today.

**Plan Comment** — feedback on a community-visible Study Plan from another Member.

**Study Session** — a Member studied on a date: minutes, domain, optional attempt, optional Resource, note, confidence after (1–5).

**Study Issue** — something a Member is stuck on: exam, domain, title, body (markdown), status (open / resolved), accepted Reply, hidden-by-moderator fields. Postgres full-text search over issues and replies answers M5.

**Reply** — a response on an Issue: body, author, optional Resource link.

**Community Event** — a scheduled gathering on the calendar: kind (`study_group` / `workshop` / `office_hours` / `mock_exam` / `social`), title, description, starts at / ends at (timestamptz), online or in person, meeting URL or location, optional exam + domain, host Member, capacity (optional), status (`scheduled` / `cancelled`), cancelled reason.

**Event RSVP** — a Member's response to an Event: `going` / `maybe` / `not_going`, updated in place (changes logged).

**Resource** — a shared study material: title, URL, type (`official_guide` / `docs` / `course` / `practice_exam` / `video` / `article` / `repo`), description, exams + domains it covers, submitted by, hidden-by-moderator fields.

**Resource Endorsement** — a Member marks a Resource as helpful. M13/O11 rank resources by endorsements from certified members and by how often passers' plan items and study sessions reference them.

**Notification** — a message the app sent (reply on your issue, comment on your plan, event changed or cancelled, exam in 7 days, certification expiring, invite): kind, target record, sent at, read at. Delivered through MaluMail.

**MCP Access Token** / **Calendar Feed Token** — hashed, revocable personal tokens. The MCP token lets a member's own AI read the community memory as that member. The feed token serves a personal iCal subscription URL (see §8).

Relationships in one line: *Invitation —becomes→ Member —has→ Exam Attempts —for→ Exam —has→ Domains; Attempt —has→ Study Plan —has→ Plan Items —cite→ Resources; Member —logs→ Study Sessions, —posts→ Issues —have→ Replies, —hosts/RSVPs→ Community Events, —endorses→ Resources.*

**Derived views, not entities:** community calendar (visible attempts ∪ scheduled events), study buddies (same exam, dates within N days), certified members (passed, `certified_until` ≥ today, result shared), at-risk members, retake eligibility (M15), pass rate (shared results only), expiring certifications.

### 3.2 Visibility rules (enforced by Postgres RLS on every read path)

| Entity | Any member sees | Owner sees | Organizer sees |
|---|---|---|---|
| Exam attempt date / exam | if `calendar_visible` | all | all |
| Attempt result | if `result_shared` | all | if shared — unshared results only as anonymous counts |
| Study plan + items + comments | if `community` | all | all |
| Study sessions | — | all | all (for at-risk, O2) |
| Issues, replies, resources, events, RSVPs | all (not hidden) | all | all, including hidden |
| Invitations | — | — | all |
| Tokens | — | own (metadata only) | — |

### 3.3 Exam catalog seed

From third-party summaries of the **v1.0 July 2026 exam guides**. **An organizer must check codes, names, and weights against the official guides before launch.** All four exams: 120 minutes, pass at 720/1000, Pearson VUE online or test center, valid for 12 months, free non-proctored renewal if on time, full exam again if the certification lapses. Retake waits after a fail: 14 days, then 30, then 90. At most 4 attempts per exam in any rolling 12 months.

| Exam | Qs | Domains (weight) |
|---|---|---|
| **CCAO-F** Claude Certified Associate – Foundations | 60 | Output Evaluation and Validation 21 · Workflow Integration and Solution Design 16 · Governance, Risk, and Responsible Use 15 · Prompting and Task Execution 14 · Product and Model Selection 12 · Configuration and Knowledge Management 12 · Troubleshooting and Optimization 10 |
| **CCDV-F** Claude Certified Developer – Foundations | 53 | Applications and Integration 33.1 · Model Selection and Optimization 16.8 · Agents and Workflows 14.7 · Prompt and Context Engineering 11.0 · Tools and MCPs 10.6 · Security and Safety 8.1 · Claude Code 3.1 · Eval, Testing, and Debugging 2.6 |
| **CCAR-F** Claude Certified Architect – Foundations | 60 | Agentic Architecture and Orchestration 27 · Claude Code Configuration and Workflows 20 · Prompt Engineering and Structured Output 20 · Tool Design and MCP Integration 18 · Context Management and Reliability 15 |
| **CCAR-P** Claude Certified Architect – Professional | 63 | Integration 19 · Solution Design and Architecture 17 · Evaluation, Testing and Optimization 16 · Governance, Safety and Risk Management 14 · Stakeholder Communication and Lifecycle Management 14 · Claude Models, Prompting and Context Engineering 13 · Developer Productivity and Operational Enablement 7 |

The retake policy lives in `community_settings` (wait days per attempt number, max attempts per 12 months). Organizers can update it without a schema change.

### 3.4 Activity memory (MaluDB, from day one)

A single `activity_log` stream, ingested into MaluDB continuously:

| Field | Example |
|---|---|
| occurred_at | 2026-09-13T14:02:11Z |
| actor_member_id | 42 |
| source | `web` / `assistant` / `mcp` / `cron` |
| action | `attempt.reschedule` |
| screen / route | `attempts-edit` · `POST /attempts/save.php` |
| entity_type, entity_id | `exam_attempt`, 117 |
| before / after (jsonb) | `{"exam_date":"2026-10-04"}` → `{"exam_date":"2026-10-25"}` |
| request_id, session_id | for tracing an assistant turn back to its request |

Event catalog, first pass:
- `screen.view` · `auth.login|logout|login_failed|2fa_enrolled`
- `invite.send|resend|accept|revoke|expire`
- `exam.create|update` · `domain.create|update|reorder`
- `attempt.create|reschedule|status_change|record_result|share_result|hide_from_calendar`
- `plan.create|update|copy|archive|visibility_change` · `plan_item.create|update|complete|reopen` · `plan_comment.create|hide`
- `session.log|update|delete`
- `issue.create|update|resolve|reopen|hide` · `reply.create|accept|hide`
- `event.create|update|cancel` · `rsvp.set`
- `resource.create|update|hide` · `resource.endorse|unendorse`
- `notification.sent` · `token.create|revoke` · `calendar_feed.fetch`
- `mcp.tool_call` · `assistant.message|action|undo`

---

## 4. Screens — the frequent questions, packaged

| Screen | Answers | Notes |
|---|---|---|
| **Dashboard** | M1, M3, M8, M9, M11, M14 | Countdown to my next exam, this week's plan items, my study minutes, upcoming community exams and events, replies waiting, cert expiry banner |
| **Calendar** | M2, M9, M11, O1 | Server-rendered month grid, HTMX prev/next. Layer toggles: exams / events. Filters: exam, event kind. Event times shown in the viewer's timezone. **At phone width it becomes an agenda list.** No JS calendar library. |
| **My Exams** (attempts) | M1, M14, M15, M17 | Create / edit / reschedule / record pass-fail / share toggle / calendar visibility / start renewal |
| **Events** | M11, M12, O10 | List + detail with RSVPs, create/edit/cancel, RSVP buttons inline |
| **Study Plans** | M3, M7, O7 | List (filter: exam, "from people who passed"), detail with items and comments, create/edit, copy plan |
| **Study Log** | M4, M10 | Quick-add row at the top, weekly totals by domain, confidence vs. domain weight chart |
| **Issues** | M5, M8, O3, O5 | List (filter: exam, domain, status, unanswered), detail with replies and accept, full-text search |
| **Resources** | M13, O11 | List (filter: exam, domain, type; sort: endorsed by certified members), detail, submit, endorse |
| **Members** | M2, M6, O6 | Directory filtered by exam / certified; profile shows visible attempts, community plans, issues, accepted answers, hosted events |
| **Organizer: Invitations** | O8, O14 | Send / resend / revoke, pending list |
| **Organizer: Exam Catalog** | — | Exams + domains CRUD, retake policy settings |
| **Organizer: Community Health** | O2, O4, O9, O12 | At-risk list, pass rates, expiring certifications, activity trend, unanswered issues |
| **Ask** (AMA page) | long tail + all A-questions | Full conversations. The command bar is on every screen. |
| **Settings** | — | Profile, timezone, notifications, 2FA, MCP tokens, calendar feed |

Voice/command-bar examples the action manifest must cover:
"move my CCAR-F exam to October twenty fifth" · "I passed" · "log forty five minutes on tool design and MCP today confidence three" · "mark week two done" · "copy Priya's plan" · "post an issue I don't get when to use subagents versus a single agent" · "schedule a CCDV-F study group next Tuesday at 7pm" · "RSVP yes to Thursday's study group" · "add this link to resources for context management" · "take me to November on the calendar" · "invite jane@example.com" (organizer)

---

## 5. Build order

**Phase 1** — Full schema (every entity above) + RLS policies + activity log + MaluDB ingestion + MCP tool surface + action manifest + slice build specs.

**Phase 2** — Auth (**invite-only** registration, email/password + Google + TOTP, MaluMail) + app shell with command bar. The organizer Invitations screen ships here because nobody can join without it.

**Phase 3 — vertical slices**
1. **Exam Catalog** (organizer) + seed data: the exemplar slice
2. **Exam Attempts + Calendar (exam layer)**
3. **Community Events + RSVPs (event layer on the calendar)**
4. **Resources + endorsements**: before plans, so plan items can link to resources
5. **Study Plans + Plan Items + comments + copy**
6. **Study Log**
7. **Issues + Replies** (+ full-text search, reply notifications)
8. **Members directory + profiles**
9. **Dashboard**: composes everything above
10. **Organizer: Community Health**
11. **Scheduled jobs** (cron): exam reminders, event reminders, cert-expiry reminders, invite expiry, calendar feed

**Phase 4** — Record + activity MCP servers, actions MCP server, unified assistant, verification against every question in §2.

---

## 6. MCP tool surface (draft — finalized in Phase 1)

**Visibility inside the MCP servers.** The read-only role runs with Postgres **row-level security** keyed on `app.member_id` (and `app.role`), set for each request from the caller's personal token or the assistant's signed context. Every tool, including `records_search`, sees only what that person can see in the UI.

**Record server** (`maludb_os_records_mcp`): `upcoming_calendar` (exams + events, date range, filters) · `member_attempts` · `study_buddies` · `retake_eligibility` · `my_certifications` · `get_study_plan` · `plan_progress` · `study_time_by_domain` · `weak_domains` · `find_issues` (full-text) · `issue_thread` · `unanswered_issues` · `find_resources` · `top_resources` · `event_details` (with RSVPs) · `certified_members` · `pass_rate` · `at_risk_members`† · `expiring_certifications`† · `pending_invitations`† · `records_search`
**Activity server** (`maludb_os_activity_mcp`): `actor_timeline` · `record_history` · `first_activity_for_exam` · `since_last_login` · `community_activity_trend`† · `activity_search`

† organizer-only (enforced by RLS/role, not just by the tool description)

---

## 7. Stack notes

- Nothing so far justifies moving beyond the baseline stack. The calendar is server-rendered, search is Postgres full-text, reminders are cron, and email is MaluMail.
- **Timezones:** events are `timestamptz` and render in the viewer's timezone. Exam attempts store a local date/time plus the member's timezone.

---

## 8. Follow-up decisions — RESOLVED 2026-09-13 (Phase 0 sign-off)

1. **Who can create events?** → **Any member** (organizers can edit or cancel any event)
2. **Who can send invites?** → **Organizers only**
3. **Recurring events?** → **v1: a "duplicate event" action only** (no recurrence rules in the schema)
4. **Renewal tracking** (12-month validity, renewal reminders)? → **Keep**
5. **Hide my exam date from the calendar?** → **Allowed, visible by default** (`calendar_visible`)
6. **Study log visibility?** → **Owner + organizers** (RLS-restricted)
7. **Personal iCal feed** (subscribe to the community calendar)? → **Keep**
8. **Retake policy + domain weights:** → **Seeded from §3.3, verified by an organizer against the official guides before launch**

**Phase 0 signed off 2026-09-13.** Proceeding to Phase 1 (full schema + RLS + activity log + MCP tool surface + action manifest + slice build specs).
