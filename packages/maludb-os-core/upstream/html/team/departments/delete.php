<?php
declare(strict_types=1);

/**
 * Action `department_delete` — log `department.delete`. Gate: `super` — the super-admin only.
 *
 * A department is deleted only while nothing works in it: no person or agent is a live member,
 * nobody is named its manager, no department reports to it, it owns no application, no
 * invitation into it is open, and no ledger statement line or eval set names it — each of
 * those is refused by name (department_delete_blockers()). The four standing departments are
 * never deleted. What goes with the row — its past memberships, approval policies, skill
 * assignments and access grants — is counted into the log, and the log carries what the
 * department was, since the id alone names nothing afterwards. The directory's change feed
 * reports the deletion from that log entry, so an application's mirror drops its row.
 * Born after the cut-over: no template, so a refusal says its own words (respond_invalid).
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('department');
if ($id === null || ($department = find_department($pdo, $id)) === null) {
    http_response_code(404);
    exit('Department not found.');
}

check_approval($pdo, 'department_delete', 'department.delete', 'Delete department ' . $department['name'],
    ['department' => $id], 'department', $id);

$goes = department_delete_cascade($pdo, $id);
try {
    $deleted = delete_department($pdo, $id);
} catch (RuntimeException $ex) {
    emit_action_status(false, ['errors' => [$ex->getMessage()]]);
    respond_invalid([$ex->getMessage()]);
}
if (!$deleted) {
    emit_action_status(false, ['errors' => ['The department could not be deleted.']]);
    respond_invalid(['The department could not be deleted.']);
}

log_activity($pdo, 'department.delete', 'department', $id, [
    'before' => [
        'name' => $department['name'],
        'description' => $department['description'],
        'parent_id' => $department['parent_id'] !== null ? (int) $department['parent_id'] : null,
        'home_location_id' => $department['home_location_id'] !== null ? (int) $department['home_location_id'] : null,
        'monthly_budget_amount' => $department['monthly_budget_amount'],
        'budget_currency' => $department['budget_currency'],
        'had_handbook' => $department['handbook_markdown'] !== null && $department['handbook_markdown'] !== '',
        'went_with_it' => $goes,
    ],
]);
emit_action_status(true, ['did' => 'Deleted department ' . $department['name'], 'refresh' => 'departmentChanged']);
hx_trigger('departmentChanged');
header('HX-Push-Url: /team/departments');
