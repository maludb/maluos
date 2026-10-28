<?php
declare(strict_types=1);

/** Action `department_remove_member` — log `department_member.remove`. Gate: admin of that department. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/team/render.php';

require_business_admin();
require_post();
verify_csrf();

$pdo = db();
$departmentId = request_integer('department');
$memberId = request_integer('member');
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

check_approval($pdo, 'department_remove_member', 'department_member.remove',
    'Remove ' . $member['display_name'] . ' from ' . $department['name'],
    ['department' => $departmentId, 'member' => $memberId], 'department', $departmentId);

remove_department_member($pdo, $departmentId, $memberId);
log_activity($pdo, 'department_member.remove', 'department', $departmentId, [
    'before' => ['member_id' => $memberId],
]);
emit_action_status(true, ['did' => 'Removed ' . $member['display_name'] . ' from ' . $department['name']]);
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
