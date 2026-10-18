<?php
declare(strict_types=1);

/** Action `application_health_check` — log `application.health_check`. Gate: insider — anyone who works here may ask whether a thing is up. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';
applications_require_files();

require_insider();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('application');
if ($id === null || ($application = find_application($pdo, $id)) === null) {
    http_response_code(404);
    exit('Application not found.');
}

$result = check_application_health($pdo, $id);

log_activity($pdo, 'application.health_check', 'application', $id, [
    'before' => ['health_status' => $application['health_status']],
    'after' => ['health_status' => $result['health_status'], 'detail' => $result['detail']],
]);
emit_action_status(true, ['did' => $application['name'] . ': ' . $result['detail'], 'refresh' => 'applicationChanged']);
hx_trigger('applicationChanged');
render_application_page($pdo, $id, 'overview');
