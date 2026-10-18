<?php
declare(strict_types=1);

/** Action `application_token_revoke` — the application's token stops working now. Super-admin. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';
applications_require_files();

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('application');
if ($id === null || ($application = find_application($pdo, $id)) === null) {
    emit_action_status(false, ['errors' => ['Application not found.']]);
    json_error('not_found', 'Application not found.', 404);
}
$n = revoke_application_tokens($pdo, $id);
log_activity($pdo, 'application.token_revoke', 'application', $id, ['after' => ['revoked' => $n]]);
emit_action_status(true, ['did' => $n > 0 ? 'Revoked the application token for ' . $application['name'] : $application['name'] . ' had no live token', 'refresh' => 'applicationChanged']);
render_application_page($pdo, $id, 'overview');
