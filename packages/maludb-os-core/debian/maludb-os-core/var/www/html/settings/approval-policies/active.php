<?php
declare(strict_types=1);

/** Action `approval_policy_set_active` — super. Event `approval_policy.set_active`. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/approvals/policies.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('policy');
if ($id === null || ($policy = find_approval_policy($pdo, $id)) === null) {
    http_response_code(404);
    exit('Policy not found.');
}
$active = request_bool('active');
set_approval_policy_active($pdo, $id, $active);
log_activity($pdo, 'approval_policy.set_active', 'approval_policy', $id, [
    'before' => ['active' => !empty($policy['active'])], 'after' => ['active' => $active, 'name' => $policy['name']],
]);
emit_action_status(true, ['did' => ($active ? 'Switched on ' : 'Switched off ') . $policy['name'], 'refresh' => 'approvalPoliciesChanged']);
header('HX-Push-Url: /settings/approval-policies');
