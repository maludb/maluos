<?php
declare(strict_types=1);

/**
 * Action `application_scope_remove` — log `application_scope.remove`. Gate: mod:applications;
 * confirm. The installation stops serving that site or department (db/141): every live grant on the
 * scope is revoked by trigger in the same statement, and the count is logged. The application drops
 * the scope's access on its next directory sync; its data there is the application's to keep.
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
$scopeId = request_integer('scope');
if ($id === null || ($application = find_application($pdo, $id)) === null) {
    emit_action_status(false, ['errors' => ['Application not found.']]);
    json_error('not_found', 'Application not found.', 404);
}
$scope = $scopeId === null ? null : find_application_scope($pdo, $scopeId);
if ($scope === null || (int) $scope['application_id'] !== $id) {
    $refuse(['That scope is not one this application serves.']);
}

check_approval($pdo, 'application_scope_remove', 'application_scope.remove',
    $application['name'] . ' stops serving ' . $scope['scope_name'] . ' (' . (int) $scope['live_grant_count'] . ' grants revoked)',
    ['application' => $id, 'scope' => $scopeId], 'application', $id);

try {
    $pdo->beginTransaction();
    $revoked = remove_application_scope($pdo, $scopeId, (int) current_member_id());
    if ($revoked === null) {
        $pdo->rollBack();
        $refuse(['That scope was already removed.']);
    }
    log_activity($pdo, 'application_scope.remove', 'application', $id, [
        'before' => ['scope_id' => $scopeId, 'location_id' => $scope['location_id'], 'department_id' => $scope['department_id'],
                     'name' => $scope['scope_name']],
        'after' => ['grants_revoked' => $revoked],
    ]);
    $pdo->commit();
} catch (PDOException $ex) {
    if ($pdo->inTransaction()) {
        $pdo->rollBack();
    }
    error_log('application scope remove failed: ' . $ex->getMessage());
    $refuse([application_trigger_message($ex, 'The scope could not be removed.')]);
}

$did = $application['name'] . ' no longer serves ' . $scope['scope_name'] . ($revoked > 0 ? ' — ' . $revoked . ' grant' . ($revoked === 1 ? '' : 's') . ' revoked' : '');
emit_action_status(true, ['did' => $did, 'refresh' => 'applicationChanged']);
if (wants_json()) {
    respond_saved(['did' => $did, 'location' => '/applications/' . $id]);
}
render_application_page($pdo, $id, 'overview');
