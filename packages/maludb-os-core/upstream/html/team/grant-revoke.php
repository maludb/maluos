<?php
declare(strict_types=1);

/** Action `module_grant_revoke` — log `module_grant.revoke`. Gate: admin over that person. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/team/queries.php';
require_once dirname(__DIR__, 2) . '/app/features/team/render.php';

require_business_admin();
require_post();
verify_csrf();

$pdo = db();
$memberId = request_integer('member');
$module = request_string('module');

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

check_approval($pdo, 'module_grant_revoke', 'module_grant.revoke',
    'Revoke ' . $module, ['member' => $memberId, 'module' => $module], 'member', $memberId);

$existing = member_module_grants($pdo, $memberId)[$module] ?? null;
revoke_module_grant($pdo, $memberId, $module);
log_activity($pdo, 'module_grant.revoke', 'member', $memberId, [
    'before' => $existing === null ? null : ['module' => $module, 'access' => $existing['access']],
    'after' => ['module' => $module, 'access' => null],
]);
emit_action_status(true, ['did' => 'Revoked ' . $module]);
hx_trigger('grantChanged');
render_member_access_page($pdo, $memberId);
