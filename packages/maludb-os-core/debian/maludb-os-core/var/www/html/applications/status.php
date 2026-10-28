<?php
declare(strict_types=1);

/**
 * Action `application_set_status` — log `application.set_status`. Gate: mod:applications.
 * Retiring is a status, not a delete — nothing cascades; live access grants and endpoints stay
 * exactly as they are.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';
applications_require_files();

require_module_grant('applications');
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('application');
$status = request_string('status');
if ($id === null || ($application = find_application($pdo, $id)) === null) {
    http_response_code(404);
    exit('Application not found.');
}
if (!in_array($status, APPLICATION_STATUSES, true)) {
    render_application_page($pdo, $id, 'overview', ['Status is planned, active, degraded or retired.']);
}

check_approval($pdo, 'application_set_status', 'application.set_status',
    'Set ' . $application['name'] . ' to ' . $status, ['application' => $id, 'status' => $status],
    'application', $id);

$after = set_application_status($pdo, $id, $status);
if ($after === []) {
    render_application_page($pdo, $id, 'overview', ['The status could not be changed.']);
}
// A retired application keeps no key to the directory (A4).
$revoked = $status === 'retired' ? revoke_application_tokens($pdo, $id) : 0;

log_activity($pdo, 'application.set_status', 'application', $id, [
    'before' => ['status' => $application['status']],
    'after' => ['status' => $after['status'], 'tokens_revoked' => $revoked],
]);
emit_action_status(true, ['did' => 'Set ' . $after['name'] . ' to ' . $status, 'refresh' => 'applicationChanged']);
hx_trigger('applicationChanged');
render_application_page($pdo, $id, 'overview');
