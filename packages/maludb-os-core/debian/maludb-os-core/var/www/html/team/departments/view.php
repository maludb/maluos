<?php
declare(strict_types=1);

/** Department detail (screen `department-view`). Gate: admin. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';

require_business_admin();

$pdo = db();
$id = request_integer('id');
if ($id === null || ($department = find_department($pdo, $id)) === null) {
    http_response_code(404);
    exit('Department not found.');
}

log_screen_view($pdo, 'department-view');
if (wants_json()) {
    require_once dirname(__DIR__, 3) . '/app/features/team/present.php';
    require_once dirname(__DIR__, 3) . '/app/features/records/present.php';
    $holdings = department_member_applications($pdo, $id);
    respond_screen([
        'department' => present_department($department),
        'members' => array_map(static fn (array $m): array => present_department_member($m) + [
            'applications' => array_map('present_member_application', $holdings[(int) $m['member_id']] ?? []),
        ], department_members($pdo, $id)),
        'applications' => array_map('present_department_application', department_applications($pdo, $id)),
        'options' => ['members' => array_map('present_member_option', selectable_members($pdo))],
        // Only the super-admin may delete, and never a standing department; only the super-admin pays for the check.
        'can' => ['delete' => is_super_admin() && empty($department['is_system'])],
        'delete_blockers' => is_super_admin() && empty($department['is_system']) ? department_delete_blockers($pdo, $id) : [],
        // Everything that names the department, blockers first — the page's whole picture of it.
        'ties' => array_map(static fn (array $t): array => present_department_tie($t, is_super_admin()), department_ties($pdo, $id)),
    ]);
}
$pageHtml = view('team/department.php', [
    'department' => $department,
    'members' => department_members($pdo, $id),
    'selectable' => selectable_members($pdo),
]);
render_screen($department['name'] . ' · Departments · ' . business_name($pdo), $pageHtml,
    ['activeNav' => 'nav-departments', 'screen' => 'department-view', 'entity' => 'department', 'recordId' => (string) $id]);
