<?php
declare(strict_types=1);

/**
 * Members directory + profile query functions. READ-ONLY slice. Every query respects the
 * viewer's §3.2 visibility: certifications only from shared results, attempts only when
 * calendar_visible or shared, plans only when community, issues/replies only when not
 * hidden. No query exposes anything the viewer couldn't already see elsewhere.
 */

const MEMBERS_PAGE_SIZE = 25;
const MEMBER_SORTS = ['name' => 'm.display_name ASC', 'joined' => 'm.joined_at DESC'];

function find_members(PDO $pdo, string $q = '', ?int $takingExamId = null, ?int $certifiedExamId = null, string $sort = 'name', int $page = 1): array
{
    $order = MEMBER_SORTS[$sort] ?? MEMBER_SORTS['name'];
    $page = max(1, $page);
    $offset = ($page - 1) * MEMBERS_PAGE_SIZE;

    $conds = ["m.status = 'active'"];
    $params = [];
    if ($q !== '') { $conds[] = 'm.display_name ILIKE :q'; $params['q'] = '%' . $q . '%'; }
    if ($takingExamId !== null) {
        $conds[] = "EXISTS (SELECT 1 FROM exam_attempts a WHERE a.member_id = m.id AND a.exam_id = :taking AND a.calendar_visible AND a.status IN ('considering','scheduled','taken'))";
        $params['taking'] = $takingExamId;
    }
    if ($certifiedExamId !== null) {
        $conds[] = "EXISTS (SELECT 1 FROM exam_attempts a WHERE a.member_id = m.id AND a.exam_id = :cert AND a.status = 'passed' AND a.result_shared AND a.certified_until >= current_date)";
        $params['cert'] = $certifiedExamId;
    }
    $where = 'WHERE ' . implode(' AND ', $conds);

    $sql = "
        SELECT m.id, m.display_name, m.organization, m.bio, m.role, m.joined_at,
               (SELECT string_agg(DISTINCT e.code, ', ' ORDER BY e.code) FROM exam_attempts a JOIN exams e ON e.id = a.exam_id
                  WHERE a.member_id = m.id AND a.status = 'passed' AND a.result_shared AND a.certified_until >= current_date) AS certified_codes,
               (SELECT string_agg(DISTINCT e.code, ', ' ORDER BY e.code) FROM exam_attempts a JOIN exams e ON e.id = a.exam_id
                  WHERE a.member_id = m.id AND a.calendar_visible AND a.status IN ('considering','scheduled','taken')) AS taking_codes,
               count(*) OVER() AS total_count
        FROM members m
        {$where}
        ORDER BY {$order}
        LIMIT :lim OFFSET :off
    ";
    $st = $pdo->prepare($sql);
    foreach ($params as $k => $v) { $st->bindValue($k, $v); }
    $st->bindValue('lim', MEMBERS_PAGE_SIZE, PDO::PARAM_INT);
    $st->bindValue('off', $offset, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}

function find_member_profile(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare("SELECT id, display_name, organization, bio, role, joined_at FROM members WHERE id = :id AND status = 'active'");
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** Shared, unexpired passes (certifications). */
function member_certifications(PDO $pdo, int $id): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT e.code, e.name, a.certified_on, a.certified_until
        FROM exam_attempts a JOIN exams e ON e.id = a.exam_id
        WHERE a.member_id = :id AND a.status = 'passed' AND a.result_shared AND a.certified_until >= current_date
        ORDER BY a.certified_until
    SQL);
    $st->execute(['id' => $id]);
    return $st->fetchAll();
}

/** Attempts the viewer may see (calendar_visible or shared, or the viewer is the member). Results masked unless shared/own. */
function member_visible_attempts(PDO $pdo, int $id, int $viewerId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT e.code AS exam_code, a.kind, a.exam_date, a.date_is_tentative,
               CASE WHEN a.member_id = :viewer OR a.result_shared THEN a.status
                    WHEN a.status IN ('passed','not_passed') THEN 'taken' ELSE a.status END AS status
        FROM exam_attempts a JOIN exams e ON e.id = a.exam_id
        WHERE a.member_id = :id
          AND (a.calendar_visible OR a.result_shared OR a.member_id = :viewer)
          AND a.status IN ('scheduled','taken','passed','not_passed')
        ORDER BY a.exam_date DESC NULLS LAST
    SQL);
    $st->execute(['id' => $id, 'viewer' => $viewerId]);
    return $st->fetchAll();
}

/** Their community-visible plans. */
function member_community_plans(PDO $pdo, int $id): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT p.id, p.title, e.code AS exam_code,
               (SELECT count(*) FROM study_plans c WHERE c.copied_from_plan_id = p.id) AS times_copied
        FROM study_plans p JOIN exams e ON e.id = p.exam_id
        WHERE p.member_id = :id AND p.visibility = 'community' AND p.status = 'active'
        ORDER BY p.created_at DESC
    SQL);
    $st->execute(['id' => $id]);
    return $st->fetchAll();
}

/** Issues they authored (not hidden). */
function member_issues(PDO $pdo, int $id): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT i.id, i.title, i.status, e.code AS exam_code
        FROM study_issues i LEFT JOIN exams e ON e.id = i.exam_id
        WHERE i.author_id = :id AND i.hidden_at IS NULL
        ORDER BY i.created_at DESC LIMIT 20
    SQL);
    $st->execute(['id' => $id]);
    return $st->fetchAll();
}

/** Replies of theirs that were accepted (a "helper" signal, O6). */
function member_accepted_answers(PDO $pdo, int $id): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT i.id, i.title, e.code AS exam_code
        FROM replies r
        JOIN study_issues i ON i.accepted_reply_id = r.id
        LEFT JOIN exams e ON e.id = i.exam_id
        WHERE r.author_id = :id AND r.hidden_at IS NULL AND i.hidden_at IS NULL
        ORDER BY i.updated_at DESC LIMIT 20
    SQL);
    $st->execute(['id' => $id]);
    return $st->fetchAll();
}

/** Upcoming events they host. */
function member_hosted_events(PDO $pdo, int $id): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT ev.id, ev.title, ev.kind, ev.starts_at, e.code AS exam_code
        FROM community_events ev LEFT JOIN exams e ON e.id = ev.exam_id
        WHERE ev.host_id = :id AND ev.status = 'scheduled' AND ev.starts_at >= now()
        ORDER BY ev.starts_at LIMIT 20
    SQL);
    $st->execute(['id' => $id]);
    return $st->fetchAll();
}

function member_exam_options(PDO $pdo): array
{
    return $pdo->query('SELECT id, code, name FROM exams WHERE active ORDER BY sort_order, code')->fetchAll();
}
