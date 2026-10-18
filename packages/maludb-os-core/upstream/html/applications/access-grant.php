<?php
declare(strict_types=1);

/**
 * Action `application_access_grant` — log `application_access.grant`. Gate: super — the roles a grant
 * gives are rights inside the application (2026-09-27). On an application that publishes roles,
 * `roles[]` is the set the grant gives (db/145); the grant's capability is the highest of them.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';
applications_require_files();

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('application');
if ($id === null || ($application = find_application($pdo, $id)) === null) {
    http_response_code(404);
    exit('Application not found.');
}
[$fields, $errors] = access_grant_fields_from_request();
if ($errors !== []) {
    render_application_access_page($pdo, $id, $errors);
}

$granteeLabel = 'that grantee';
if ($fields['member_id'] !== null) {
    $st = $pdo->prepare('SELECT display_name FROM members WHERE id = :id');
    $st->execute(['id' => $fields['member_id']]);
    $granteeLabel = (string) ($st->fetchColumn() ?: ('member #' . $fields['member_id']));
} elseif ($fields['department_id'] !== null) {
    $st = $pdo->prepare('SELECT name FROM departments WHERE id = :id');
    $st->execute(['id' => $fields['department_id']]);
    $granteeLabel = (string) ($st->fetchColumn() ?: ('department #' . $fields['department_id']));
} elseif ($fields['resident_location_id'] !== null) {
    $st = $pdo->prepare('SELECT name FROM locations WHERE id = :id');
    $st->execute(['id' => $fields['resident_location_id']]);
    $granteeLabel = 'everyone at ' . (string) ($st->fetchColumn() ?: ('location #' . $fields['resident_location_id']));
}
$what = $fields['roles'] !== [] ? implode(', ', $fields['roles']) : $fields['capability'];

check_approval($pdo, 'application_access_grant', 'application_access.grant',
    'Grant ' . $what . ' on ' . $application['name'] . ' to ' . $granteeLabel,
    array_merge(['application' => $id], $fields), 'application', $id);

$pdo->beginTransaction();
try {
    $grant = grant_application_access($pdo, $id, $fields, (int) current_member_id());
    $pdo->commit();
} catch (PDOException $ex) {
    $pdo->rollBack();
    render_application_access_page($pdo, $id, [application_trigger_message($ex, 'That access grant could not be saved.')]);
}
if ($grant === []) {
    render_application_access_page($pdo, $id, ['That access grant could not be saved.']);
}

log_activity($pdo, 'application_access.grant', 'application', $id, [
    'after' => [
        'application_access_id' => $grant['application_access_id'] ?? null,
        'member_id' => $fields['member_id'], 'department_id' => $fields['department_id'],
        'resident_location_id' => $fields['resident_location_id'],
        'scope_id' => $grant['scope_id'] ?? null, 'scope_name' => $grant['scope_name'] ?? null,
        'role_key' => $grant['role_key'] ?? null, 'roles' => $fields['roles'],
        'capability' => $grant['capability'] ?? $fields['capability'],
    ],
]);
$where = ($grant['scope_name'] ?? null) !== null ? ' at ' . $grant['scope_name'] : '';
emit_action_status(true, ['did' => 'Granted ' . ($fields['roles'] !== [] ? application_role_names($pdo, $id, $fields['roles']) : ($grant['capability'] ?? $what)) . ' on '
                          . $application['name'] . $where . ' to ' . $granteeLabel,
                          'record_id' => (int) ($grant['application_access_id'] ?? 0),
                          'refresh' => 'applicationChanged']);
hx_trigger('applicationChanged');
render_application_access_page($pdo, $id);
