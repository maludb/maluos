<?php
declare(strict_types=1);

/**
 * Screen `approval-policies-settings` — /settings/approval-policies (docs/build-specs/approvals.md).
 * Anyone who works here may read what needs approval (mcp_approval_policies is insider-open);
 * only a super-admin is offered the buttons.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/approvals/policies.php';

require_insider();

$pdo = db();
log_screen_view($pdo, 'approval-policies-settings');
respond_screen([
    'policies' => array_map('present_approval_policy', find_approval_policies($pdo)),
    'can' => ['edit' => is_super_admin()],
]);
