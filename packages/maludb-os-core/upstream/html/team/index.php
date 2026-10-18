<?php
declare(strict_types=1);

/**
 * People & access (screen `team-list`) — the human half of HR since the sidebar merge of
 * 2026-09-18; reached from the HR screen, not from an entry of its own.
 * Gate: admin — administration, not a module grant.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/team/queries.php';

require_business_admin();

$pdo = db();
$q = request_string('q');
$kind = request_string('kind', 'both');
$role = request_string('role');
$departmentId = request_integer('department');
$page = request_integer('page') ?? 1;

$members = team_members($pdo, $q, $departmentId, $kind, $role, 'display_name', $page);
$total = (int) ($members[0]['total_count'] ?? 0);
$totalPages = max(1, (int) ceil($total / TEAM_PAGE_SIZE));

if (wants_json()) {
    require_once dirname(__DIR__, 2) . '/app/features/team/present.php';
    require_once dirname(__DIR__, 2) . '/app/features/records/present.php';
    log_screen_view($pdo, 'team-list');
    respond_screen([
        'members' => array_map('present_team_member_row', $members),
        'pagination' => ['page' => $page, 'total_pages' => $totalPages, 'total' => $total],
        'filters' => ['q' => $q, 'kind' => $kind, 'role' => $role,
                      'department' => $departmentId === null ? '' : (string) $departmentId],
        'options' => ['departments' => array_map('present_department_option', find_departments($pdo))],
    ]);
}

if (($_SERVER['HTTP_HX_TARGET'] ?? '') === 'team-list-results') {
    header('Vary: HX-Request');
    echo view('team/partials/table.php',
        ['members' => $members, 'page' => $page, 'totalPages' => $totalPages, 'q' => $q]);
    exit;
}

log_screen_view($pdo, 'team-list');
$pageHtml = view('team/page.php', [
    'members' => $members, 'q' => $q, 'kind' => $kind, 'role' => $role,
    'departmentId' => $departmentId, 'departments' => find_departments($pdo),
    'page' => $page, 'totalPages' => $totalPages,
]);
render_screen('People & access · ' . business_name($pdo), $pageHtml,
    ['activeNav' => 'nav-agents', 'screen' => 'team-list']);
