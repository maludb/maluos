<?php
declare(strict_types=1);

/**
 * Action `application_endpoint_save` — log `application_endpoint.save`, carrying name, kind and
 * agent_reachable in `after` (changing that flag changes what agents can be granted). Gate:
 * mod:applications. Two levels under html/ — dirname(__DIR__, 3), not 2.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/applications/render.php';
applications_require_files();

require_module_grant('applications');
require_post();
verify_csrf();

$pdo = db();
$epId = request_integer('endpoint');
$appId = request_integer('application');
$before = null;
$application = null;

if ($epId !== null) {
    $before = find_application_endpoint($pdo, $epId);
    if ($before === null) {
        http_response_code(404);
        exit('Endpoint not found.');
    }
    $application = find_application($pdo, (int) $before['application_id']);
} else {
    if ($appId === null || ($application = find_application($pdo, $appId)) === null) {
        http_response_code(404);
        exit('Application not found.');
    }
}

[$fields, $errors] = endpoint_fields_from_request();
if ($epId === null) {
    $fields['application_id'] = $appId;
}

$renderForm = function (array $errs) use ($pdo, $epId, $application, $fields): never {
    emit_action_status(false, ['errors' => $errs]);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    echo view('applications/endpoint-form.php', [
        'application' => $application,
        'endpoint' => array_merge($fields, $epId !== null ? ['application_endpoint_id' => $epId] : []),
        'isEdit' => $epId !== null,
        'errors' => $errs,
    ]);
    exit;
};

if ($errors !== []) {
    $renderForm($errors);
}

check_approval($pdo, 'application_endpoint_save', 'application_endpoint.save',
    ($epId === null ? 'Add endpoint: ' : 'Update endpoint: ') . $fields['name'] . ' on ' . $application['name'],
    $fields, 'application_endpoint', $epId);

try {
    $endpoint = upsert_application_endpoint($pdo, $epId, $fields);
} catch (PDOException $ex) {
    error_log('endpoint save failed: ' . $ex->getMessage());
    if ($ex->getCode() === '23505') {
        $renderForm(['An endpoint with that name already exists on this application.']);
    }
    $renderForm([application_trigger_message($ex, 'The endpoint could not be saved.')]);
}
if ($endpoint === []) {
    $renderForm(['The endpoint could not be saved.']);
}

log_activity($pdo, 'application_endpoint.save', 'application_endpoint', (int) $endpoint['application_endpoint_id'], [
    'before' => $before,
    'after' => ['name' => $endpoint['name'], 'kind' => $endpoint['kind'], 'agent_reachable' => $endpoint['agent_reachable']],
]);
emit_action_status(true, ['did' => ($epId === null ? 'Added endpoint ' : 'Updated endpoint ') . $endpoint['name'],
                          'refresh' => 'applicationChanged']);
hx_trigger('applicationChanged');
render_application_page($pdo, (int) $application['application_id'], 'endpoints');
