<?php
declare(strict_types=1);

/**
 * Action `application_access_change` — log `application_access.change`. Gate: super, as granting and
 * revoking are (2026-09-27).
 *
 * Changes the roles a live grant gives (`roles[]`, db/145 — or its capability, on an application
 * that declares no roles). The old grant is revoked and a new one made for the same grantee and scope in one
 * transaction (change_application_access()), so the history says who held what, when.
 * Born after the cut-over: no template, so a refusal says its own words (respond_invalid).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';
applications_require_files();

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('application');
$grantId = request_integer('application_access');
if ($grantId === null || $id === null || ($application = find_application($pdo, $id)) === null) {
    http_response_code(404);
    exit('Application not found.');
}
$roles = access_roles_from_request();
$capability = request_string('capability', 'read');
$errors = [];
if ($roles === [] && !in_array($capability, ACCESS_CAPABILITIES, true)) {
    $errors[] = 'Capability is read, write or admin.';
}
foreach ($roles as $r) {
    if (!preg_match('/^[a-z][a-z0-9_]{0,39}$/', $r)) {
        $errors[] = $r . ' is not one of this application\'s roles.';
    }
}
$roleKey = null;   // the grant's role_key is the highest of $roles (grant_application_access())
if (!in_array($capability, ACCESS_CAPABILITIES, true)) {
    $capability = 'read';   // replaced by the role's capability
}
if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);
}

check_approval($pdo, 'application_access_change', 'application_access.change',
    'Change access grant #' . $grantId . ' on ' . $application['name'] . ' to ' . ($roles !== [] ? implode(', ', $roles) : $capability),
    ['application' => $id, 'application_access' => $grantId, 'roles' => $roles, 'capability' => $capability],
    'application', $id);

$pdo->beginTransaction();
try {
    $before = application_grant_roles($pdo, $id)[$grantId] ?? [];
    $changed = change_application_access($pdo, $id, $grantId, $roleKey, $capability, (int) current_member_id(), $roles);
} catch (PDOException $ex) {
    $pdo->rollBack();
    $message = application_trigger_message($ex, 'That access grant could not be changed.');
    emit_action_status(false, ['errors' => [$message]]);
    respond_invalid([$message]);
}
if ($changed === []) {
    $pdo->rollBack();
    emit_action_status(false, ['errors' => ['That grant is not live on this application.']]);
    respond_invalid(['That grant is not live on this application.']);
}
$pdo->commit();
$after = $changed[1];

$held = static fn (array $g): array => [
    'application_access_id' => (int) $g['application_access_id'],
    'member_id' => $g['member_id'] !== null ? (int) $g['member_id'] : null,
    'department_id' => $g['department_id'] !== null ? (int) $g['department_id'] : null,
    'resident_location_id' => $g['resident_location_id'] !== null ? (int) $g['resident_location_id'] : null,
    'scope_id' => $g['scope_id'] !== null ? (int) $g['scope_id'] : null, 'scope_name' => $g['scope_name'],
    'role_key' => $g['role_key'], 'capability' => $g['capability'],
];
log_activity($pdo, 'application_access.change', 'application', $id, [
    'before' => $held($changed[0]) + ['roles' => array_column($before, 'role_key')],
    'after' => $held($after) + ['roles' => $roles],
]);

$grantee = $after['member_name'] ?? $after['department_name']
    ?? ('everyone at ' . ($after['resident_location_name'] ?? 'that site'));
$where = ($after['scope_name'] ?? null) !== null ? ' at ' . $after['scope_name'] : '';
emit_action_status(true, ['did' => 'Changed ' . $grantee . ' to ' . ($roles !== [] ? application_role_names($pdo, $id, $roles) : $after['capability'])
                          . ' on ' . $application['name'] . $where,
                          'record_id' => (int) $after['application_access_id'],
                          'refresh' => 'applicationChanged']);
hx_trigger('applicationChanged');
render_application_access_page($pdo, $id);
