<?php
declare(strict_types=1);

/** Action `member_set_role` — log `member.set_role`. Gate: super. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/team/queries.php';
require_once dirname(__DIR__, 2) . '/app/features/team/render.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$memberId = request_integer('member');
$role = request_string('business_role');

if ($memberId === null) {
    http_response_code(400);
    exit('Which member?');
}
if (!in_array($role, ['super_admin', 'dept_admin', 'user'], true)) {
    render_member_access_page($pdo, $memberId, ['That is not one of the three roles.']);
}

$before = find_team_member($pdo, $memberId);
if ($before === null) {
    http_response_code(404);
    exit('Member not found.');
}
// An agent is always a user (the schema enforces it too) — say so rather than let the
// constraint surface as a database error.
if (($before['member_kind'] ?? 'human') === 'agent' && $role !== 'user') {
    render_member_access_page($pdo, $memberId, ['Agents are always users. Only a human can administer.']);
}
if ($memberId === current_member_id() && $role !== 'super_admin') {
    render_member_access_page($pdo, $memberId, ['You cannot remove your own super-admin role.']);
}

check_approval($pdo, 'member_set_role', 'member.set_role',
    'Set ' . ($before['display_name'] ?? 'member') . ' to ' . $role,
    ['member' => $memberId, 'business_role' => $role], 'member', $memberId);

$after = set_member_role($pdo, $memberId, $role);
log_activity($pdo, 'member.set_role', 'member', $memberId, [
    'before' => ['business_role' => $before['business_role']],
    'after' => ['business_role' => $role],
]);
emit_action_status(true, ['did' => 'Role updated']);
hx_trigger('memberChanged');
render_member_access_page($pdo, $memberId);
