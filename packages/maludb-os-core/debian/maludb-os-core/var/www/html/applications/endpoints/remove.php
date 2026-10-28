<?php
declare(strict_types=1);

/**
 * Action `application_endpoint_remove` — log `application_endpoint.remove`. Gate:
 * mod:applications. Two levels under html/ — dirname(__DIR__, 3), not 2.
 *
 * Refused while a live agent_tool_grants row points at the endpoint, naming the agents —
 * checked proactively here (the retire_location() pattern, app/features/estate/queries.php)
 * rather than only from a caught PDOException: agent_tool_grants.application_endpoint_id is
 * ON DELETE RESTRICT but a revoked grant row is never deleted (only revoked_at is stamped), so
 * a literal hard delete would stay blocked forever even after the blocking grant is revoked.
 * remove_application_endpoint() retires the endpoint (status change) instead of deleting it —
 * see that function's own docblock for the full reasoning.
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
if ($epId === null || ($endpoint = find_application_endpoint($pdo, $epId)) === null) {
    http_response_code(404);
    exit('Endpoint not found.');
}
$application = find_application($pdo, $appId ?? (int) $endpoint['application_id']);
if ($application === null) {
    http_response_code(404);
    exit('Application not found.');
}

check_approval($pdo, 'application_endpoint_remove', 'application_endpoint.remove',
    'Remove endpoint ' . $endpoint['name'] . ' on ' . $application['name'],
    ['endpoint' => $epId], 'application_endpoint', $epId);

$dependents = endpoint_dependents($pdo, $epId);
if ($dependents !== []) {
    render_application_page($pdo, (int) $application['application_id'], 'endpoints', [
        'This endpoint cannot be removed yet — agent tool grants still point at it: '
        . implode(', ', $dependents) . '. Revoke those grants first.',
    ]);
}

try {
    $ok = remove_application_endpoint($pdo, $epId);
} catch (PDOException $ex) {
    render_application_page($pdo, (int) $application['application_id'], 'endpoints', [
        application_trigger_message($ex, 'That endpoint could not be removed.'),
    ]);
}
if (!$ok) {
    render_application_page($pdo, (int) $application['application_id'], 'endpoints', ['That endpoint could not be removed.']);
}

log_activity($pdo, 'application_endpoint.remove', 'application_endpoint', $epId, [
    'before' => ['name' => $endpoint['name'], 'kind' => $endpoint['kind']],
]);
emit_action_status(true, ['did' => 'Removed endpoint ' . $endpoint['name'] . ' on ' . $application['name'],
                          'refresh' => 'applicationChanged']);
hx_trigger('applicationChanged');
render_application_page($pdo, (int) $application['application_id'], 'endpoints');
