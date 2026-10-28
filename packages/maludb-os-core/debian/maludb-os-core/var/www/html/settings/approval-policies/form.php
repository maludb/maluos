<?php
declare(strict_types=1);

/** Screens `approval-policy-add` / `approval-policy-edit` — super. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/approvals/policies.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/records/present.php';   // present_member_option(), present_department_option()

require_super_admin();

$pdo = db();
$id = request_integer('id');
$policy = $id !== null ? find_approval_policy($pdo, $id) : null;
if ($id !== null && $policy === null) {
    http_response_code(404);
    exit('Policy not found.');
}
log_screen_view($pdo, $id === null ? 'approval-policy-add' : 'approval-policy-edit');

$members = selectable_members($pdo);
$named = static fn (array $labels): array => array_map(
    static fn (string $k, string $v): array => ['id' => $k, 'name' => $v], array_keys($labels), $labels);
respond_screen([
    'policy' => present_approval_policy($policy ?? ['applies_to' => 'agents', 'category' => 'money_out', 'expires_after_hours' => 72, 'active' => true]),
    'options' => [
        'categories' => $named(APPROVAL_POLICY_CATEGORIES),
        'applies_to' => $named(APPROVAL_POLICY_APPLIES_TO),
        'agents' => array_values(array_map('present_member_option', array_filter($members, static fn (array $m): bool => ($m['member_kind'] ?? '') === 'agent'))),
        'approvers' => array_values(array_map('present_member_option', array_filter($members, static fn (array $m): bool => ($m['member_kind'] ?? '') !== 'agent'))),
        'departments' => array_map('present_department_option', find_departments($pdo)),
    ],
    'base_currency' => base_currency($pdo),
]);
