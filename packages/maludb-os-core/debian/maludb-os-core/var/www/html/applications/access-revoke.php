<?php
declare(strict_types=1);

/** Action `application_access_revoke` — log `application_access.revoke`. Gate: super (2026-09-27). */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';
applications_require_files();

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$grantId = request_integer('application_access');
$id = request_integer('application');
if ($grantId === null || $id === null || ($application = find_application($pdo, $id)) === null) {
    http_response_code(404);
    exit('Application not found.');
}

check_approval($pdo, 'application_access_revoke', 'application_access.revoke',
    'Revoke access grant #' . $grantId . ' on ' . $application['name'],
    ['application' => $id, 'application_access' => $grantId], 'application', $id);

$ok = revoke_application_access($pdo, $grantId, (int) current_member_id(), $id);
if (!$ok) {
    render_application_access_page($pdo, $id, ['That access grant could not be revoked.']);
}

log_activity($pdo, 'application_access.revoke', 'application', $id, [
    'before' => ['application_access_id' => $grantId],
]);
emit_action_status(true, ['did' => 'Revoked access grant on ' . $application['name'], 'refresh' => 'applicationChanged']);
hx_trigger('applicationChanged');
render_application_access_page($pdo, $id);
