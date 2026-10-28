<?php
declare(strict_types=1);

/**
 * Action `application_sme_set` — name the agent that is an application's subject matter expert,
 * or clear it (no `agent`). Log `application.sme_set`. Gate: mod:applications (require_module_grant).
 * Active applications only. Naming an expert grants nothing: an expert who cannot use the
 * application shows as a gap until someone grants the access on purpose. JSON only (db/130).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';
applications_require_files();

require_module_grant('applications');
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('application');
if ($id === null || ($application = find_application($pdo, $id)) === null) {
    http_response_code(404);
    emit_action_status(false, ['errors' => ['Application not found.']]);
    exit('Application not found.');
}
$agentId = request_integer('agent');

$errors = [];
if (!in_array($application['status'], APPLICATION_RUNNING_STATUSES, true) || empty($application['module_enabled'])) {
    $errors[] = 'Only an active application has an expert.';
}
$agent = null;
if ($agentId !== null) {
    foreach (application_expert_options($pdo) as $option) {
        if ((int) $option['member_id'] === $agentId) {
            $agent = $option;
        }
    }
    if ($agent === null) {
        $errors[] = 'The expert is one of the business\'s active agents.';
    }
}
if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);
}

check_approval($pdo, 'application_sme_set', 'application.sme_set',
    ($agent === null ? 'Clear the expert of ' : 'Name ' . $agent['display_name'] . ' expert of ') . $application['name'],
    ['application' => $id, 'agent' => $agentId], 'application', $id);

if (!set_application_expert($pdo, $id, $agentId)) {
    emit_action_status(false, ['errors' => ['The expert could not be saved.']]);
    respond_invalid(['The expert could not be saved.']);
}

log_activity($pdo, 'application.sme_set', 'application', $id, [
    'before' => ['sme_agent_member_id' => $application['sme_agent_member_id'] !== null ? (int) $application['sme_agent_member_id'] : null],
    'after' => ['sme_agent_member_id' => $agentId],
]);
emit_action_status(true, [
    'did' => $agent === null ? 'Cleared the expert of ' . $application['name']
                             : $agent['display_name'] . ' is now the expert on ' . $application['name'],
    'refresh' => 'applicationChanged',
]);
