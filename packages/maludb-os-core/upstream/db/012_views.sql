-- 012_views.sql
-- The ENTIRE read surface for the MCP servers. Every view is owned by the migration
-- role (so it can read base tables) and embeds the §3.2 visibility rules as SQL, keyed
-- on app_current_member_id() / app_is_organizer(). The read MCP roles are granted SELECT
-- on these views and NOTHING on base tables — so purposeful tools AND the arbitrary
-- records_search / activity_search tools are all confined to what the caller may see.
--
-- security_barrier = true stops the planner from pushing a caller's WHERE clause below
-- the visibility predicate (a classic RLS/leaky-view hole). These views are NOT
-- security_invoker: they intentionally run with the owner's rights so the read roles
-- need no base-table grants; the embedded predicate is the guard.

BEGIN;

-- ==========================================================================
-- RECORD MEMORY VIEWS  (granted to app_records_ro)
-- ==========================================================================

-- Members directory (M2, M6, O6). Non-sensitive columns only — no email, no auth.
CREATE OR REPLACE VIEW mcp_member_directory WITH (security_barrier = true) AS
SELECT m.id AS member_id, m.display_name, m.timezone, m.bio, m.organization,
       m.role, m.status, m.joined_at
FROM members m
WHERE app_current_member_id() IS NOT NULL          -- any signed-in member sees the directory
  AND m.status = 'active';

-- Exam catalog + domains (reference data; visible to all members).
CREATE OR REPLACE VIEW mcp_exams WITH (security_barrier = true) AS
SELECT e.* FROM exams e
WHERE app_current_member_id() IS NOT NULL;

CREATE OR REPLACE VIEW mcp_exam_domains WITH (security_barrier = true) AS
SELECT d.id AS domain_id, d.exam_id, e.code AS exam_code, d.name, d.weight, d.sort_order
FROM exam_domains d JOIN exams e ON e.id = d.exam_id
WHERE app_current_member_id() IS NOT NULL;

-- Exam attempts with RESULT MASKING (§3.2). A row is visible if the caller owns it, or
-- it is calendar_visible, or its result is shared, or the caller is an organizer.
-- The result (pass/fail + cert dates) is revealed only to the owner or when shared;
-- otherwise a taken attempt reads as status 'taken' with null cert dates.
CREATE OR REPLACE VIEW mcp_attempts WITH (security_barrier = true) AS
SELECT
    a.id AS attempt_id, a.member_id, m.display_name AS member_name,
    a.exam_id, e.code AS exam_code, e.name AS exam_name,
    a.kind, a.exam_date, a.start_time, a.timezone, a.delivery, a.date_is_tentative,
    a.calendar_visible, a.result_shared,
    CASE
        WHEN a.member_id = app_current_member_id() OR a.result_shared THEN a.status
        WHEN a.status IN ('passed','not_passed') THEN 'taken'
        ELSE a.status
    END AS status,
    CASE WHEN a.member_id = app_current_member_id() OR a.result_shared
         THEN a.certified_on END AS certified_on,
    CASE WHEN a.member_id = app_current_member_id() OR a.result_shared
         THEN a.certified_until END AS certified_until,
    a.created_at, a.updated_at
FROM exam_attempts a
JOIN members m ON m.id = a.member_id
JOIN exams   e ON e.id = a.exam_id
WHERE a.member_id = app_current_member_id()
   OR a.calendar_visible
   OR a.result_shared
   OR app_is_organizer();

-- Community calendar (M2, M9, M11, O1): exams layer ∪ events layer, one shape.
CREATE OR REPLACE VIEW mcp_calendar WITH (security_barrier = true) AS
SELECT 'exam'::text AS entry_kind, a.attempt_id AS entry_id,
       (a.exam_code || ' — ' || a.member_name) AS title,
       a.exam_date::timestamptz AS starts_at, NULL::timestamptz AS ends_at,
       a.exam_code, NULL::text AS event_kind, a.member_id AS person_id,
       a.member_name AS person_name, a.delivery AS location_hint
FROM mcp_attempts a
WHERE a.exam_date IS NOT NULL
  AND a.status IN ('scheduled','taken','passed','not_passed')
  AND (a.calendar_visible OR a.member_id = app_current_member_id() OR app_is_organizer())
UNION ALL
SELECT 'event'::text, ev.id,
       ev.title, ev.starts_at, ev.ends_at,
       e.code AS exam_code, ev.kind AS event_kind, ev.host_id,
       h.display_name, COALESCE(ev.location, ev.meeting_url)
FROM community_events ev
JOIN members h ON h.id = ev.host_id
LEFT JOIN exams e ON e.id = ev.exam_id
WHERE ev.status = 'scheduled'
  AND app_current_member_id() IS NOT NULL;

-- Study buddies (M2): for the current member, others with a visible attempt for the
-- same exam within the community's buddy window of the member's own attempt date.
CREATE OR REPLACE VIEW mcp_study_buddies WITH (security_barrier = true) AS
SELECT mine.exam_id, e.code AS exam_code, mine.exam_date AS my_exam_date,
       buddy.member_id AS buddy_member_id, bm.display_name AS buddy_name,
       buddy.exam_date AS buddy_exam_date,
       (buddy.exam_date - mine.exam_date) AS days_apart
FROM exam_attempts mine
JOIN exams e ON e.id = mine.exam_id
CROSS JOIN LATERAL (SELECT study_buddy_window_days AS w FROM community_settings) cs
JOIN exam_attempts buddy
     ON buddy.exam_id = mine.exam_id
    AND buddy.member_id <> mine.member_id
    AND buddy.calendar_visible
    AND buddy.status IN ('scheduled','considering')
    AND buddy.exam_date IS NOT NULL
    AND abs(buddy.exam_date - mine.exam_date) <= cs.w
JOIN members bm ON bm.id = buddy.member_id AND bm.status = 'active'
WHERE mine.member_id = app_current_member_id()
  AND mine.exam_date IS NOT NULL;

-- Certified members (M6, and the ranking input for M13): passed, unexpired, shared.
CREATE OR REPLACE VIEW mcp_certified_members WITH (security_barrier = true) AS
SELECT DISTINCT a.member_id, m.display_name, a.exam_id, e.code AS exam_code,
       a.certified_on, a.certified_until
FROM exam_attempts a
JOIN members m ON m.id = a.member_id AND m.status = 'active'
JOIN exams   e ON e.id = a.exam_id
WHERE a.status = 'passed'
  AND a.result_shared
  AND a.certified_until >= current_date
  AND app_current_member_id() IS NOT NULL;

-- Study plans (M3, M7, O7): community plans, own plans, organizer sees all.
CREATE OR REPLACE VIEW mcp_study_plans WITH (security_barrier = true) AS
SELECT p.id AS plan_id, p.member_id, m.display_name AS member_name,
       p.attempt_id, p.exam_id, e.code AS exam_code, p.title, p.approach,
       p.visibility, p.status, p.copied_from_plan_id,
       (SELECT count(*) FROM study_plans c WHERE c.copied_from_plan_id = p.id) AS times_copied,
       p.created_at, p.updated_at
FROM study_plans p
JOIN members m ON m.id = p.member_id
JOIN exams   e ON e.id = p.exam_id
WHERE p.visibility = 'community'
   OR p.member_id = app_current_member_id()
   OR app_is_organizer();

-- Plan items of visible plans, with progress helper columns.
CREATE OR REPLACE VIEW mcp_plan_items WITH (security_barrier = true) AS
SELECT i.id AS item_id, i.plan_id, i.domain_id, d.name AS domain_name,
       i.title, i.notes, i.due_date, i.resource_id, i.sort_order, i.completed_at
FROM plan_items i
JOIN mcp_study_plans p ON p.plan_id = i.plan_id      -- inherits plan visibility
LEFT JOIN exam_domains d ON d.id = i.domain_id;

-- Plan progress (M3): "am I on track" = completed vs. due-by-today.
CREATE OR REPLACE VIEW mcp_plan_progress WITH (security_barrier = true) AS
SELECT p.plan_id, p.member_id, p.exam_code, p.title,
       count(i.item_id)                                            AS items_total,
       count(i.item_id) FILTER (WHERE i.completed_at IS NOT NULL)  AS items_completed,
       count(i.item_id) FILTER (WHERE i.due_date <= current_date)  AS items_due_by_today,
       count(i.item_id) FILTER (WHERE i.due_date <= current_date
                                  AND i.completed_at IS NULL)       AS items_overdue,
       (count(i.item_id) FILTER (WHERE i.due_date <= current_date AND i.completed_at IS NULL) = 0)
                                                                    AS on_track
FROM mcp_study_plans p
LEFT JOIN mcp_plan_items i ON i.plan_id = p.plan_id
GROUP BY p.plan_id, p.member_id, p.exam_code, p.title;

-- Plan comments on visible plans (M8).
CREATE OR REPLACE VIEW mcp_plan_comments WITH (security_barrier = true) AS
SELECT c.id AS comment_id, c.plan_id, c.author_id, a.display_name AS author_name,
       c.body, c.created_at
FROM plan_comments c
JOIN mcp_study_plans p ON p.plan_id = c.plan_id
JOIN members a ON a.id = c.author_id;

-- Study sessions (M4, M10, O2): owner + organizers only (§8.6).
CREATE OR REPLACE VIEW mcp_study_sessions WITH (security_barrier = true) AS
SELECT s.id AS session_id, s.member_id, s.attempt_id, s.exam_id, e.code AS exam_code,
       s.domain_id, d.name AS domain_name, s.resource_id, s.studied_on, s.minutes,
       s.confidence, s.note, s.created_at
FROM study_sessions s
LEFT JOIN exams e ON e.id = s.exam_id
LEFT JOIN exam_domains d ON d.id = s.domain_id
WHERE s.member_id = app_current_member_id()
   OR app_is_organizer();

-- Study time & confidence by domain (M4 weak domains, M10 monthly totals). Own data.
CREATE OR REPLACE VIEW mcp_study_time_by_domain WITH (security_barrier = true) AS
SELECT s.member_id, s.exam_id, s.exam_code, s.domain_id, s.domain_name,
       date_trunc('month', s.studied_on)::date AS month,
       sum(s.minutes) AS total_minutes,
       round(avg(s.confidence)::numeric, 2) AS avg_confidence,
       count(*) AS session_count
FROM mcp_study_sessions s
GROUP BY s.member_id, s.exam_id, s.exam_code, s.domain_id, s.domain_name,
         date_trunc('month', s.studied_on);

-- Issues (M5, M8, O3, O5): non-hidden to all; own + organizer see hidden.
CREATE OR REPLACE VIEW mcp_issues WITH (security_barrier = true) AS
SELECT i.id AS issue_id, i.author_id, au.display_name AS author_name,
       i.exam_id, e.code AS exam_code, i.domain_id, d.name AS domain_name,
       i.title, i.body, i.status, i.accepted_reply_id,
       (i.hidden_at IS NOT NULL) AS is_hidden,
       (SELECT count(*) FROM replies r WHERE r.issue_id = i.id AND r.hidden_at IS NULL) AS reply_count,
       i.search_tsv, i.created_at, i.updated_at
FROM study_issues i
JOIN members au ON au.id = i.author_id
LEFT JOIN exams e ON e.id = i.exam_id
LEFT JOIN exam_domains d ON d.id = i.domain_id
WHERE app_current_member_id() IS NOT NULL
  AND (i.hidden_at IS NULL OR i.author_id = app_current_member_id() OR app_is_organizer());

-- Replies of visible issues.
CREATE OR REPLACE VIEW mcp_replies WITH (security_barrier = true) AS
SELECT r.id AS reply_id, r.issue_id, r.author_id, au.display_name AS author_name,
       r.body, r.resource_id, (r.hidden_at IS NOT NULL) AS is_hidden,
       (i.accepted_reply_id = r.id) AS is_accepted, r.created_at
FROM replies r
JOIN mcp_issues i ON i.issue_id = r.issue_id       -- inherits issue visibility
JOIN members au ON au.id = r.author_id
WHERE r.hidden_at IS NULL OR r.author_id = app_current_member_id() OR app_is_organizer();

-- Unanswered issues (O5).
CREATE OR REPLACE VIEW mcp_unanswered_issues WITH (security_barrier = true) AS
SELECT i.* FROM mcp_issues i WHERE i.reply_count = 0 AND NOT i.is_hidden;

-- Events with RSVP counts (M11, M12, O10). All members see events.
CREATE OR REPLACE VIEW mcp_events WITH (security_barrier = true) AS
SELECT ev.id AS event_id, ev.host_id, h.display_name AS host_name, ev.kind, ev.title,
       ev.description, ev.starts_at, ev.ends_at, ev.is_online, ev.meeting_url,
       ev.location, ev.exam_id, e.code AS exam_code, ev.domain_id, ev.capacity,
       ev.status, ev.cancelled_reason,
       count(rs.id) FILTER (WHERE rs.response = 'going')  AS going_count,
       count(rs.id) FILTER (WHERE rs.response = 'maybe')  AS maybe_count,
       ev.created_at
FROM community_events ev
JOIN members h ON h.id = ev.host_id
LEFT JOIN exams e ON e.id = ev.exam_id
LEFT JOIN event_rsvps rs ON rs.event_id = ev.id
WHERE app_current_member_id() IS NOT NULL
GROUP BY ev.id, h.display_name, e.code;

-- Who's coming (M12): RSVPs visible within the community.
CREATE OR REPLACE VIEW mcp_event_rsvps WITH (security_barrier = true) AS
SELECT rs.event_id, rs.member_id, m.display_name AS member_name, rs.response, rs.updated_at
FROM event_rsvps rs
JOIN members m ON m.id = rs.member_id
WHERE app_current_member_id() IS NOT NULL;

-- Resources with ranking signals (M13, O11): endorsements, certified-endorser count,
-- and passer-usage (plan items + sessions by certified members that reference it).
CREATE OR REPLACE VIEW mcp_resources WITH (security_barrier = true) AS
SELECT r.id AS resource_id, r.submitted_by, sb.display_name AS submitted_by_name,
       r.title, r.url, r.type, r.description, (r.hidden_at IS NOT NULL) AS is_hidden,
       (SELECT count(*) FROM resource_endorsements en WHERE en.resource_id = r.id) AS endorsement_count,
       (SELECT count(*) FROM resource_endorsements en
         WHERE en.resource_id = r.id
           AND EXISTS (SELECT 1 FROM exam_attempts a
                        WHERE a.member_id = en.member_id AND a.status = 'passed'
                          AND a.result_shared AND a.certified_until >= current_date)
       ) AS certified_endorsement_count,
       r.search_tsv, r.created_at
FROM resources r
JOIN members sb ON sb.id = r.submitted_by
WHERE app_current_member_id() IS NOT NULL
  AND (r.hidden_at IS NULL OR r.submitted_by = app_current_member_id() OR app_is_organizer());

-- Resource coverage join for filtering by exam/domain (M13, O11).
CREATE OR REPLACE VIEW mcp_resource_coverage WITH (security_barrier = true) AS
SELECT r.resource_id, re.exam_id, rd.domain_id
FROM mcp_resources r
LEFT JOIN resource_exams   re ON re.resource_id = r.resource_id
LEFT JOIN resource_domains rd ON rd.resource_id = r.resource_id;

-- Pass rate (O4): anonymous aggregate from SHARED results only. Visible to all members
-- (no member identity is exposed).
CREATE OR REPLACE VIEW mcp_pass_rate WITH (security_barrier = true) AS
SELECT e.id AS exam_id, e.code AS exam_code, e.name AS exam_name,
       count(*) FILTER (WHERE a.status IN ('passed','not_passed') AND a.result_shared) AS results_shared,
       count(*) FILTER (WHERE a.status = 'passed' AND a.result_shared) AS passed_shared,
       CASE WHEN count(*) FILTER (WHERE a.status IN ('passed','not_passed') AND a.result_shared) > 0
            THEN round(100.0 * count(*) FILTER (WHERE a.status = 'passed' AND a.result_shared)
                       / count(*) FILTER (WHERE a.status IN ('passed','not_passed') AND a.result_shared), 1)
       END AS pass_rate_pct
FROM exams e
LEFT JOIN exam_attempts a ON a.exam_id = e.id
WHERE app_current_member_id() IS NOT NULL
GROUP BY e.id, e.code, e.name;

-- My certifications (M14): own passed attempts, expiry, renewal window.
CREATE OR REPLACE VIEW mcp_my_certifications WITH (security_barrier = true) AS
SELECT a.id AS attempt_id, a.exam_id, e.code AS exam_code, e.name AS exam_name,
       a.certified_on, a.certified_until,
       (a.certified_until - current_date) AS days_until_expiry,
       (a.certified_until < current_date) AS expired
FROM exam_attempts a
JOIN exams e ON e.id = a.exam_id
WHERE a.member_id = app_current_member_id() AND a.status = 'passed';

-- Retake eligibility (M15): own fail history + policy → earliest next attempt date.
-- Aggregate per exam first, then apply the policy (from the single-row settings) so we
-- never subscript a scalar subquery or group by the settings array.
CREATE OR REPLACE VIEW mcp_retake_eligibility WITH (security_barrier = true) AS
SELECT agg.exam_id, agg.exam_code, agg.prior_fails, agg.attempts_last_12mo,
       cs.max_attempts_per_12mo, agg.last_fail_date,
       CASE WHEN agg.last_fail_date IS NOT NULL THEN
           (agg.last_fail_date
              + cs.retake_wait_days[least(agg.prior_fails, array_length(cs.retake_wait_days, 1))]
                * interval '1 day')::date
       END AS earliest_retake_date
FROM (
    SELECT a.exam_id, e.code AS exam_code,
           count(*) FILTER (WHERE a.status = 'not_passed')::int AS prior_fails,
           count(*) FILTER (WHERE a.status IN ('taken','passed','not_passed')
                              AND a.exam_date > current_date - interval '12 months')::int AS attempts_last_12mo,
           max(a.exam_date) FILTER (WHERE a.status = 'not_passed') AS last_fail_date
    FROM exam_attempts a
    JOIN exams e ON e.id = a.exam_id
    WHERE a.member_id = app_current_member_id()
    GROUP BY a.exam_id, e.code
) agg
CROSS JOIN community_settings cs;

-- Organizer-only: at-risk members (O2). Upcoming attempt but no plan, or no study in N days.
CREATE OR REPLACE VIEW mcp_at_risk_members WITH (security_barrier = true) AS
SELECT m.id AS member_id, m.display_name, a.exam_id, e.code AS exam_code, a.exam_date,
       (a.exam_date - current_date) AS days_to_exam,
       NOT EXISTS (SELECT 1 FROM study_plans p WHERE p.member_id = m.id AND p.attempt_id = a.id) AS no_plan,
       (SELECT max(s.studied_on) FROM study_sessions s WHERE s.member_id = m.id) AS last_studied_on
FROM exam_attempts a
JOIN members m ON m.id = a.member_id AND m.status = 'active'
JOIN exams e ON e.id = a.exam_id
CROSS JOIN LATERAL (SELECT at_risk_no_study_days AS d FROM community_settings) cs
WHERE app_is_organizer()
  AND a.status = 'scheduled' AND a.exam_date >= current_date
  AND (
        NOT EXISTS (SELECT 1 FROM study_plans p WHERE p.member_id = m.id AND p.attempt_id = a.id)
     OR COALESCE((SELECT max(s.studied_on) FROM study_sessions s WHERE s.member_id = m.id),
                 date '1900-01-01') < current_date - cs.d
      );

-- Organizer-only: certifications expiring in the next 60 days (O9).
CREATE OR REPLACE VIEW mcp_expiring_certifications WITH (security_barrier = true) AS
SELECT a.member_id, m.display_name, a.exam_id, e.code AS exam_code,
       a.certified_until, (a.certified_until - current_date) AS days_until_expiry
FROM exam_attempts a
JOIN members m ON m.id = a.member_id
JOIN exams e ON e.id = a.exam_id
WHERE app_is_organizer()
  AND a.status = 'passed'
  AND a.certified_until BETWEEN current_date AND current_date + 60;

-- Organizer-only: pending invitations (O8, O14).
CREATE OR REPLACE VIEW mcp_pending_invitations WITH (security_barrier = true) AS
SELECT iv.id AS invitation_id, iv.email, iv.role_granted, ib.display_name AS invited_by_name,
       iv.expires_at, iv.created_at
FROM invitations iv
JOIN members ib ON ib.id = iv.invited_by
WHERE app_is_organizer()
  AND iv.accepted_at IS NULL AND iv.revoked_at IS NULL;

-- ==========================================================================
-- ACTIVITY MEMORY VIEWS  (granted to app_activity_ro)
-- ==========================================================================

-- My activity trail (M16, M17, M18): the caller's own actions.
CREATE OR REPLACE VIEW mcp_activity_my WITH (security_barrier = true) AS
SELECT al.id, al.occurred_at, al.source, al.action, al.screen, al.route,
       al.entity_type, al.entity_id, al.before, al.after, al.request_id
FROM activity_log al
WHERE al.actor_member_id = app_current_member_id();

-- Record history (M17 own reschedules; O15 moderation audit for organizers).
CREATE OR REPLACE VIEW mcp_activity_record_history WITH (security_barrier = true) AS
SELECT al.id, al.occurred_at, al.actor_member_id, m.display_name AS actor_name,
       al.source, al.action, al.entity_type, al.entity_id, al.before, al.after
FROM activity_log al
LEFT JOIN members m ON m.id = al.actor_member_id
WHERE al.actor_member_id = app_current_member_id() OR app_is_organizer();

-- Community feed of public actions (M19 "what changed since I last logged in").
-- Only public, non-hidden create-type actions are exposed to members.
CREATE OR REPLACE VIEW mcp_activity_community_feed WITH (security_barrier = true) AS
SELECT al.id, al.occurred_at, al.action, al.entity_type, al.entity_id
FROM activity_log al
WHERE app_current_member_id() IS NOT NULL
  AND al.action IN ('issue.create','reply.create','event.create',
                    'resource.create','plan.create');

-- Organizer-only: full stream for trends (O12) and moderation audit (O15).
CREATE OR REPLACE VIEW mcp_activity_community WITH (security_barrier = true) AS
SELECT al.id, al.occurred_at, al.actor_member_id, m.display_name AS actor_name,
       al.source, al.action, al.screen, al.route, al.entity_type, al.entity_id,
       al.before, al.after, al.request_id
FROM activity_log al
LEFT JOIN members m ON m.id = al.actor_member_id
WHERE app_is_organizer();

-- ==========================================================================
-- GRANTS — the read roles see ONLY these views.
-- ==========================================================================
GRANT SELECT ON
    mcp_member_directory, mcp_exams, mcp_exam_domains, mcp_attempts, mcp_calendar,
    mcp_study_buddies, mcp_certified_members, mcp_study_plans, mcp_plan_items,
    mcp_plan_progress, mcp_plan_comments, mcp_study_sessions, mcp_study_time_by_domain,
    mcp_issues, mcp_replies, mcp_unanswered_issues, mcp_events, mcp_event_rsvps,
    mcp_resources, mcp_resource_coverage, mcp_pass_rate, mcp_my_certifications,
    mcp_retake_eligibility, mcp_at_risk_members, mcp_expiring_certifications,
    mcp_pending_invitations
TO app_records_ro;

GRANT SELECT ON
    mcp_activity_my, mcp_activity_record_history, mcp_activity_community_feed,
    mcp_activity_community
TO app_activity_ro;

COMMIT;
