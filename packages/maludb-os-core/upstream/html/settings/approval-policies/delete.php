<?php
declare(strict_types=1);

/**
 * Action `approval_policy_delete` — super. Event `approval_policy.delete`. The requests the policy
 * caught keep their history (policy_id is SET NULL).
 */
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
check_approval($pdo, 'approval_policy_delete', 'approval_policy.delete', 'Delete the approval policy ' . $policy['name'],
    ['policy' => $id], 'approval_policy', $id);
delete_approval_policy($pdo, $id);
log_activity($pdo, 'approval_policy.delete', 'approval_policy', $id, [
    'before' => ['name' => $policy['name'], 'action_pattern' => $policy['action_pattern'], 'category' => $policy['category']],
]);
emit_action_status(true, ['did' => 'Deleted policy ' . $policy['name'], 'refresh' => 'approvalPoliciesChanged']);
header('HX-Push-Url: /settings/approval-policies');
