<?php
declare(strict_types=1);

/**
 * Action `application_token_mint` — mint (or rotate) the application's own token for the kernel's
 * directory, ledger and chat endpoints (A4; OS_APPLICATION_TOKEN in its config/.env). Super-admin.
 * One live token per application; minting again revokes the last. The value is in this answer's
 * own field and nowhere else — never in `did`, which is logged.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';
applications_require_files();

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('application');
$refuse = static function (string $message, int $status = 422): never {
    emit_action_status(false, ['errors' => [$message]]);
    if ($status === 422) { respond_invalid([$message]); }
    json_error($status === 404 ? 'not_found' : 'forbidden', $message, $status);
};
if ($id === null || ($application = find_application($pdo, $id)) === null) {
    $refuse('Application not found.', 404);
}
if (!empty($application['is_builtin'])) {
    $refuse('The operating system\'s own applications need no token.');
}
if (!in_array($application['status'], ['active', 'degraded'], true)) {
    $refuse('Only an active application holds a token; this one is ' . $application['status'] . '.');
}
$t = mint_application_token($pdo, $id, (int) current_member_id(), $application['name'] . ' (application token)');
log_activity($pdo, 'application.token_mint', 'application', $id, ['after' => ['token_id' => $t['id']]]);
emit_action_status(true, ['did' => 'Minted the application token for ' . $application['name'], 'refresh' => 'applicationChanged']);
if (wants_json()) {
    respond_saved(['did' => 'Minted the application token for ' . $application['name'], 'token' => $t['raw']]);
}
render_application_page($pdo, $id, 'overview');
