# MCP Tool Surface — Phase 1

Status: **draft for Phase 1 sign-off** · 2026-09-13
Derived from the Phase 0 question list (plan §2) and the schema in `db/`. Two client-facing read servers; the actions server is separate (see `docs/action-manifest.md`).

Both servers are **read-only** (`readOnlyHint: true` on every tool), Python + FastMCP, streamable-HTTP/stateless-JSON transport, one runtime. Each connects with its own PostgreSQL role and reads **only the `mcp_*` views** in `db/012_views.sql` — never base tables. Visibility (plan §3.2) is enforced in those views, keyed on the request context the server sets from the caller's token:

```sql
SELECT set_config('app.member_id', $token_member_id, false);
SELECT set_config('app.role',      $token_role,      false);
```

Because the roles can touch nothing but the views, the guarded `records_search` / `activity_search` tools are safe by construction — an arbitrary SELECT still sees only what the caller may see. Every tool call is itself logged to the activity stream (`mcp.tool_call`).

Roles: **`app_records_ro`** (record server) · **`app_activity_ro`** (activity server). Neither has `BYPASSRLS`; neither has base-table grants. `statement_timeout` and a hard row cap are set on both search tools.

---

## Record server — `maludb_os_records_mcp` (role `app_records_ro`)

| Tool | Answers | Backing view(s) | Key params |
|---|---|---|---|
| `upcoming_calendar` | M2, M9, M11, O1 | `mcp_calendar` | `from` date, `to` date, `entry_kind?` (exam/event), `exam_code?`, `event_kind?` |
| `member_attempts` | M1, M17*, O1 | `mcp_attempts` | `member_id?` (default caller), `exam_code?`, `status?` |
| `study_buddies` | M2 | `mcp_study_buddies` | `exam_code?` (default: all my upcoming) |
| `retake_eligibility` | M15 | `mcp_retake_eligibility` | `exam_code?` |
| `my_certifications` | M1, M14 | `mcp_my_certifications` | `include_expired?` (bool) |
| `get_study_plan` | M3, M7 | `mcp_study_plans` + `mcp_plan_items` | `plan_id` |
| `find_study_plans` | M7, O7 | `mcp_study_plans` | `exam_code?`, `from_passers?` (bool), `sort?` (recent/most_copied), `limit` |
| `plan_progress` | M3 | `mcp_plan_progress` | `plan_id?` (default: my active plans) |
| `study_time_by_domain` | M4, M10 | `mcp_study_time_by_domain` | `exam_code?`, `month?` |
| `weak_domains` | M4 | `mcp_study_time_by_domain` + `mcp_exam_domains` | `exam_code` (ranks low confidence + low time vs. domain weight) |
| `find_issues` | M5 | `mcp_issues` (FTS on `search_tsv`) | `q` (full-text), `exam_code?`, `domain?`, `status?`, `limit` |
| `issue_thread` | M5, M8 | `mcp_issues` + `mcp_replies` | `issue_id` |
| `unanswered_issues` | O5 | `mcp_unanswered_issues` | `exam_code?`, `domain?`, `limit` |
| `find_resources` | M13 | `mcp_resources` + `mcp_resource_coverage` | `q?`, `exam_code?`, `domain?`, `type?`, `sort?` (endorsed/certified_endorsed/recent) |
| `top_resources` | M13, O11 | `mcp_resources` + `mcp_resource_coverage` | `exam_code`, `domain?`, `limit` (ranks by certified endorsements + passer usage) |
| `event_details` | M11, M12 | `mcp_events` + `mcp_event_rsvps` | `event_id` |
| `find_events` | M11, O10 | `mcp_events` | `from?`, `to?`, `exam_code?`, `kind?` |
| `member_profile` | M6, O6 | `mcp_member_directory` (+ visible attempts/plans/issues) | `member_id` |
| `find_members` | M2, M6 | `mcp_member_directory` | `q?`, `exam_code?` (taking), `certified_in?` (exam) |
| `certified_members` | M6 | `mcp_certified_members` | `exam_code?`, `domain?` |
| `pass_rate` | O4 | `mcp_pass_rate` | `exam_code?` (anonymous, shared results only) |
| `at_risk_members` † | O2 | `mcp_at_risk_members` | `exam_code?` |
| `expiring_certifications` † | O9 | `mcp_expiring_certifications` | `within_days?` (default 60) |
| `pending_invitations` † | O8 | `mcp_pending_invitations` | — |
| `records_search` | long tail | any `mcp_*` record view | `sql` (single SELECT, validated; timeout + row cap) |

† Returns rows only when the caller's role is `organizer` (the underlying view yields nothing otherwise — enforced in SQL, not the description).

`records_search` tool description embeds the list of readable `mcp_*` views and their columns so the agent writes correct queries.

---

## Activity server — `maludb_os_activity_mcp` (role `app_activity_ro`)

| Tool | Answers | Backing view(s) | Key params |
|---|---|---|---|
| `actor_timeline` | M18 | `mcp_activity_my` | `from?`, `to?`, `action_prefix?` |
| `first_activity_for_exam` | M16 | `mcp_activity_my` | `exam_code` (earliest `plan.create`/`session.log`/`attempt.create` for that exam) |
| `record_history` | M17, O15† | `mcp_activity_record_history` | `entity_type`, `entity_id` |
| `reschedule_count` | M17 | `mcp_activity_record_history` | `attempt_id` (counts `attempt.reschedule`) |
| `since_last_login` | M19 | `mcp_activity_community_feed` | `since?` (default: caller's `last_login_at`) |
| `community_activity_trend` † | O12 | `mcp_activity_community` | `bucket?` (day/week), `from?`, `to?` |
| `moderation_audit` † | O15 | `mcp_activity_community` | `entity_type?`, `action_prefix?` (`*.hide`, `event.cancel`, …) |
| `activity_search` | long tail | activity views the caller may read | `sql` (single SELECT, validated; timeout + row cap) |

† Organizer-only via the underlying view.

---

## Coverage check — every Phase 0 question maps to a tool

**Member:** M1 `member_attempts`/`my_certifications` · M2 `study_buddies`/`upcoming_calendar` · M3 `plan_progress` · M4 `weak_domains` · M5 `find_issues`/`issue_thread` · M6 `certified_members`/`member_profile` · M7 `find_study_plans` · M8 `issue_thread`/`get_study_plan` (+ Notifications screen) · M9 `upcoming_calendar` · M10 `study_time_by_domain` · M11 `find_events`/`upcoming_calendar` · M12 `event_details` · M13 `top_resources`/`find_resources` · M14 `my_certifications` · M15 `retake_eligibility` · M16 `first_activity_for_exam` · M17 `reschedule_count`/`record_history` · M18 `actor_timeline` · M19 `since_last_login`.

**Organizer:** O1 `upcoming_calendar`/`member_attempts` · O2 `at_risk_members` · O3 `find_issues` (group by domain) · O4 `pass_rate` · O5 `unanswered_issues` · O6 `member_profile` (accepted answers, endorsements, events hosted) · O7 `find_study_plans` (sort=most_copied) · O8 `pending_invitations` · O9 `expiring_certifications` · O10 `find_events` (RSVP counts) · O11 `top_resources` · O12 `community_activity_trend` · O13 `first_activity_for_exam` + `my_certifications` (record) combined with `record_history` (activity) · O14 `pending_invitations` + `record_history` (first login) · O15 `moderation_audit`.

No question is left without a tool.
