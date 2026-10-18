<?php
declare(strict_types=1);

/** Department form (screens `department-add` / `department-edit`). Gate: admin of that department. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';

require_business_admin();

$pdo = db();
$id = request_integer('id');
$department = [];
if ($id !== null) {
    $department = find_department($pdo, $id);
    if ($department === null) {
        http_response_code(404);
        exit('Department not found.');
    }
    require_admin_for_department($pdo, $id);
} elseif (!is_super_admin()) {
    // Creating a department is not administering one you already have.
    deny('Only the super-admin creates departments.');
}

log_screen_view($pdo, $id === null ? 'department-add' : 'department-edit');
if (wants_json()) {
    require_once dirname(__DIR__, 3) . '/app/features/team/present.php';
    require_once dirname(__DIR__, 3) . '/app/features/records/present.php';
    $allDepartments = find_departments($pdo);
    $locations = business_locations($pdo);
    // The defaults department-form.php worked out inline (db/074): everything reports to the
    // Front Office unless another department is named, and a new department starts onsite.
    $frontOffice = front_office_department($allDepartments);
    respond_screen([
        'department' => present_department($department),
        'selected_parent_id' => ((int) ($department['parent_id'] ?? 0))
            ?: ($frontOffice !== null ? (int) $frontOffice['department_id'] : null),
        'selected_location_id' => ((int) ($department['home_location_id'] ?? 0))
            ?: ($id !== null ? null : default_department_location($locations)),
        'options' => [
            'members' => array_map('present_member_option', selectable_members($pdo)),
            'departments' => array_map('present_department_option', $allDepartments),
            'locations' => array_map('present_location_option', $locations),
        ],
        'can' => ['delete' => $id !== null && is_super_admin() && empty($department['is_system'])],
        'delete_blockers' => $id !== null && is_super_admin() && empty($department['is_system']) ? department_delete_blockers($pdo, $id) : [],
        // What blocks the delete, row by row, so the refusal can say what to do about each.
        'ties' => $id !== null && is_super_admin() && empty($department['is_system'])
            ? array_map(static fn (array $t): array => present_department_tie($t, true), department_ties($pdo, $id)) : [],
    ]);
}
$pageHtml = view('team/department-form.php', [
    'department' => $department,
    'members' => selectable_members($pdo),
    'locations' => business_locations($pdo),
    'departments' => find_departments($pdo),
    'errors' => [],
]);
render_screen(($id === null ? 'New department' : 'Edit department') . ' · ' . business_name($pdo), $pageHtml,
    ['activeNav' => 'nav-departments', 'screen' => $id === null ? 'department-add' : 'department-edit',
     'entity' => 'department', 'recordId' => (string) ($id ?? '')]);
