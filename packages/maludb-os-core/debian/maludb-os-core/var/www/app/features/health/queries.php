<?php
declare(strict_types=1);

/**
 * Community-health query functions (organizer dashboards). Read-only. The SQL mirrors the
 * organizer-only mcp_* views so the screen and the AMA agent agree. Controllers gate with
 * require_organizer(); these functions assume that check has passed.
 */

/** At-risk (O2): scheduled attempt with no plan, or no study logged in the settings window. */
function at_risk_members(PDO $pdo): array
{
    $st = $pdo->query(<<<'SQL'
        SELECT m.id AS member_id, m.display_name, e.code AS exam_code, a.exam_date,
               (a.exam_date - current_date) AS days_to_exam,
               NOT EXISTS (SELECT 1 FROM study_plans p WHERE p.member_id = m.id AND p.attempt_id = a.id) AS no_plan,
               (SELECT max(s.studied_on) FROM study_sessions s WHERE s.member_id = m.id) AS last_studied_on
        FROM exam_attempts a
        JOIN members m ON m.id = a.member_id AND m.status = 'active'
        JOIN exams e ON e.id = a.exam_id
        CROSS JOIN LATERAL (SELECT at_risk_no_study_days AS d FROM community_settings) cs
        WHERE a.status = 'scheduled' AND a.exam_date >= current_date
          AND (NOT EXISTS (SELECT 1 FROM study_plans p WHERE p.member_id = m.id AND p.attempt_id = a.id)
               OR COALESCE((SELECT max(s.studied_on) FROM study_sessions s WHERE s.member_id = m.id), date '1900-01-01') < current_date - cs.d)
        ORDER BY a.exam_date
    SQL);
    return $st->fetchAll();
}

/** Pass rate (O4): shared results only, anonymous counts per exam. */
function pass_rate(PDO $pdo): array
{
    return $pdo->query(<<<'SQL'
        SELECT e.code, e.name,
               count(*) FILTER (WHERE a.status IN ('passed','not_passed') AND a.result_shared) AS results_shared,
               count(*) FILTER (WHERE a.status = 'passed' AND a.result_shared) AS passed_shared,
               CASE WHEN count(*) FILTER (WHERE a.status IN ('passed','not_passed') AND a.result_shared) > 0
                    THEN round(100.0 * count(*) FILTER (WHERE a.status = 'passed' AND a.result_shared)
                             / count(*) FILTER (WHERE a.status IN ('passed','not_passed') AND a.result_shared), 1) END AS pass_rate_pct
        FROM exams e LEFT JOIN exam_attempts a ON a.exam_id = e.id
        GROUP BY e.id, e.code, e.name ORDER BY e.sort_order
    SQL)->fetchAll();
}

/** Certifications expiring within N days (O9). */
function expiring_certifications(PDO $pdo, int $withinDays = 60): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT m.display_name, e.code, a.certified_until, (a.certified_until - current_date) AS days_left
        FROM exam_attempts a JOIN members m ON m.id = a.member_id JOIN exams e ON e.id = a.exam_id
        WHERE a.status = 'passed' AND a.certified_until BETWEEN current_date AND current_date + (:d || ' days')::interval
        ORDER BY a.certified_until
    SQL);
    $st->execute(['d' => (string) $withinDays]);
    return $st->fetchAll();
}

/** Unanswered issues (O5): open, not hidden, zero non-hidden replies. */
function unanswered_issues(PDO $pdo, int $limit = 20): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT i.id, i.title, e.code AS exam_code, au.display_name AS author_name, i.created_at
        FROM study_issues i JOIN members au ON au.id = i.author_id LEFT JOIN exams e ON e.id = i.exam_id
        WHERE i.status = 'open' AND i.hidden_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM replies r WHERE r.issue_id = i.id AND r.hidden_at IS NULL)
        ORDER BY i.created_at LIMIT :lim
    SQL);
    $st->bindValue('lim', $limit, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}

/** Activity trend (O12): distinct actors + action counts per week for the last N weeks. */
function activity_trend(PDO $pdo, int $weeks = 8): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT date_trunc('week', occurred_at)::date AS week_start,
               count(DISTINCT actor_member_id) AS active_members,
               count(*) AS actions
        FROM activity_log
        WHERE occurred_at >= date_trunc('week', current_date) - ((:w - 1) || ' weeks')::interval
        GROUP BY 1 ORDER BY 1 DESC
    SQL);
    $st->execute(['w' => $weeks]);
    return $st->fetchAll();
}

function pending_invitation_count(PDO $pdo): int
{
    return (int) $pdo->query('SELECT count(*) FROM invitations WHERE accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now()')->fetchColumn();
}
