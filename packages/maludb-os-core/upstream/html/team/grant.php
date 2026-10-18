<?php
declare(strict_types=1);

/** Action `module_grant_set` — log `module_grant.set`. Gate: admin over that person. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/team/queries.php';
require_once dirname(__DIR__, 2) . '/app/features/team/render.php';

require_business_admin();
require_post();
verify_csrf();

$pdo = db();
$memberId = request_integer('member');
$module = request_string('module');
$access = request_string('access');

if ($memberId === null) {
    http_response_code(400);
    exit('Which member?');
}
if (!can_admin_member($pdo, $memberId)) {
    deny('You do not administer this person.');
}
if (!array_key_exists($module, grantable_modules())) {
    render_member_access_page($pdo, $memberId, ['That is not a module.']);
}
if (!in_array($access, ['read', 'write'], true)) {
    render_member_access_page($pdo, $memberId, ['Access is read or write.']);
}

check_approval($pdo, 'module_grant_set', 'module_grant.set',
    'Grant ' . $module . ' (' . $access . ')',
    ['member' => $memberId, 'module' => $module, 'access' => $access], 'member', $memberId);

$existing = member_module_grants($pdo, $memberId)[$module] ?? null;
set_module_grant($pdo, $memberId, $module, $access, (int) current_member_id());
log_activity($pdo, 'module_grant.set', 'member', $memberId, [
    'before' => $existing === null ? null : ['module' => $module, 'access' => $existing['access']],
    'after' => ['module' => $module, 'access' => $access],
]);
emit_action_status(true, ['did' => 'Granted ' . $module . ' (' . $access . ')']);
hx_trigger('grantChanged');
render_member_access_page($pdo, $memberId);
