<?php
declare(strict_types=1);

/**
 * Action `application_scope_add` — log `application_scope.add`. Gate: mod:applications. One site
 * (`location`) or one department (`department`) the installation now serves (db/141); the application
 * creates it on its next directory sync — the kernel owns structure. Which of the two it takes is the
 * application's scope kind; the trigger's sentence refuses the other. Answers `record_id` = the scope.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';
applications_require_files();

require_module('applications');
require_post();
verify_csrf();

$pdo = db();
$refuse = static function (array $errors): never {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);
};
$id = request_integer('application');
if ($id === null || ($application = find_application($pdo, $id)) === null) {
    emit_action_status(false, ['errors' => ['Application not found.']]);
    json_error('not_found', 'Application not found.', 404);
}
$locationId = request_integer('location');
$departmentId = request_integer('department');
if (($locationId === null) === ($departmentId === null)) {
    $refuse(['Pick one site or one department for this application to serve.']);
}
$label = null;
if ($locationId !== null) {
    $st = $pdo->prepare('SELECT name FROM mcp_locations WHERE location_id = :id');
    $st->execute(['id' => $locationId]);
    $label = $st->fetchColumn() ?: null;
} else {
    $st = $pdo->prepare('SELECT name FROM mcp_departments WHERE department_id = :id');
    $st->execute(['id' => $departmentId]);
    $label = $st->fetchColumn() ?: null;
}
if ($label === null) {
    $refuse([$locationId !== null ? 'That site does not exist.' : 'That department does not exist.']);
}

check_approval($pdo, 'application_scope_add', 'application_scope.add',
    $application['name'] . ' serves ' . $label,
    ['application' => $id, 'location' => $locationId, 'department' => $departmentId], 'application', $id);

try {
    $scope = add_application_scope($pdo, $id, $locationId, $departmentId, (int) current_member_id());
} catch (PDOException $ex) {
    error_log('application scope add failed: ' . $ex->getMessage());
    $refuse([$ex->getCode() === '23505'
        ? $application['name'] . ' already serves ' . $label . '.'
        : application_trigger_message($ex, 'The scope could not be added.')]);
}
if ($scope === []) {
    $refuse(['The scope could not be added.']);
}

log_activity($pdo, 'application_scope.add', 'application', $id, [
    'after' => ['scope_id' => (int) $scope['scope_id'], 'location_id' => $locationId,
                'department_id' => $departmentId, 'name' => $label],
]);
$did = $application['name'] . ' now serves ' . $label;
emit_action_status(true, ['did' => $did, 'record_id' => (int) $scope['scope_id'], 'refresh' => 'applicationChanged']);
if (wants_json()) {
    respond_saved(['did' => $did, 'record_id' => (int) $scope['scope_id'], 'location' => '/applications/' . $id]);
}
render_application_page($pdo, $id, 'overview');
