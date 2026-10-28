<?php
declare(strict_types=1);

/**
 * Endpoint form (screens `application-endpoint-add` / `application-endpoint-edit`). Gate:
 * require_module_grant('applications'). Two levels under html/ — dirname(__DIR__, 3), not 2.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/applications/render.php';

require_module_grant('applications');
applications_require_files();

$pdo = db();
$id = request_integer('id');
$endpoint = [];

if ($id !== null) {
    $endpoint = find_application_endpoint($pdo, $id);
    if ($endpoint === null) {
        http_response_code(404);
        exit('Endpoint not found.');
    }
    $application = find_application($pdo, (int) $endpoint['application_id']);
} else {
    $appId = request_integer('application');
    if ($appId === null || ($application = find_application($pdo, $appId)) === null) {
        http_response_code(404);
        exit('Application not found.');
    }
    $endpoint = ['agent_reachable' => true, 'auth_kind' => 'none'];
}
if ($application === null) {
    http_response_code(404);
    exit('Application not found.');
}

log_screen_view($pdo, $id === null ? 'application-endpoint-add' : 'application-endpoint-edit');
if (wants_json()) {
    require_once dirname(__DIR__, 3) . '/app/features/applications/present.php';
    respond_screen([
        'application' => ['id' => (int) $application['application_id'], 'name' => (string) $application['name']],
        'endpoint' => present_application_endpoint($endpoint),
        'options' => ['kinds' => ENDPOINT_KINDS, 'auth_kinds' => ENDPOINT_AUTH_KINDS],
    ]);
}
render_screen(($id === null ? 'New endpoint' : 'Edit endpoint') . ' · ' . $application['name'] . ' · ' . business_name($pdo),
    view('applications/endpoint-form.php', [
        'application' => $application,
        'endpoint' => $endpoint,
        'isEdit' => $id !== null,
        'errors' => [],
    ]),
    ['activeNav' => 'nav-applications', 'screen' => $id === null ? 'application-endpoint-add' : 'application-endpoint-edit',
     'entity' => 'application_endpoint', 'recordId' => (string) ($id ?? '')]);
