<?php
declare(strict_types=1);

/** Action `approval_policy_save` — super. Event `approval_policy.save`. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/approvals/policies.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('policy');
$before = $id !== null ? find_approval_policy($pdo, $id) : null;
if ($id !== null && $before === null) {
    http_response_code(404);
    exit('Policy not found.');
}
[$fields, $errors] = approval_policy_fields_from_request($pdo);
if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);
}

try {
    $row = upsert_approval_policy($pdo, $id, $fields, (int) current_member_id());
} catch (PDOException $ex) {
    error_log('approval policy save failed: ' . $ex->getMessage());
    $message = $ex->getCode() === '23505' ? 'A policy with that name already exists.' : 'The policy could not be saved.';
    emit_action_status(false, ['errors' => [$message]]);
    respond_invalid([$message]);
}

log_activity($pdo, 'approval_policy.save', 'approval_policy', (int) $row['id'], [
    'before' => $before !== null ? ['name' => $before['name'], 'action_pattern' => $before['action_pattern'], 'amount_threshold' => $before['amount_threshold']] : null,
    'after' => ['name' => $row['name'], 'category' => $row['category'], 'action_pattern' => $row['action_pattern'],
                'applies_to' => $row['applies_to'], 'amount_threshold' => $row['amount_threshold']],
]);
emit_action_status(true, ['did' => 'Saved policy ' . $row['name'], 'refresh' => 'approvalPoliciesChanged']);
header('HX-Push-Url: /settings/approval-policies/' . (int) $row['id'] . '/edit');   // the saved policy (owner, 2026-09-27: land on the record)
