<?php
declare(strict_types=1);

/**
 * Action `department_add_member` — log `department_member.create`. Gate: admin of that
 * department. The is_admin flag is set here too: it is what makes a dept-admin an
 * administrator of this department and an ordinary user everywhere else.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/team/render.php';

require_business_admin();
require_post();
verify_csrf();

$pdo = db();
$departmentId = request_integer('department');
$memberId = request_integer('member');
$isAdmin = request_bool('is_admin');
$isPrimary = request_bool('is_primary');
$back = request_string('back');

if ($departmentId === null || $memberId === null) {
    http_response_code(400);
    exit('Which member, and which department?');
}
require_admin_for_department($pdo, $departmentId);
if (!can_admin_member($pdo, $memberId)) {
    deny('You do not administer this person.');
}

$department = find_department($pdo, $departmentId);
$member = find_team_member($pdo, $memberId);
if ($department === null || $member === null) {
    http_response_code(404);
    exit('Not found.');
}

check_approval($pdo, 'department_add_member', 'department_member.create',
    'Add ' . $member['display_name'] . ' to ' . $department['name'],
    ['department' => $departmentId, 'member' => $memberId, 'is_admin' => $isAdmin, 'is_primary' => $isPrimary],
    'department', $departmentId);

$row = add_department_member($pdo, $departmentId, $memberId, $isAdmin, $isPrimary);
log_activity($pdo, 'department_member.create', 'department', $departmentId, [
    'after' => ['member_id' => $memberId, 'is_admin' => $isAdmin, 'is_primary' => $isPrimary],
]);
emit_action_status(true, ['did' => 'Updated ' . $member['display_name'] . ' in ' . $department['name']]);
hx_trigger('departmentChanged');

if ($back === 'department') {
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    header('HX-Push-Url: /team/departments/' . $departmentId);
    echo view('team/department.php', [
        'department' => find_department($pdo, $departmentId),
        'members' => department_members($pdo, $departmentId),
        'selectable' => selectable_members($pdo),
    ]);
    exit;
}
render_member_access_page($pdo, $memberId);
