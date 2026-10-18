<?php
declare(strict_types=1);

/**
 * Action `agent_set_manager` — log `agent.set_manager`. Gate: mod:hr. Refuses a non-human
 * manager, naming the rule (agent_profiles.manager_member_id: "human (app-enforced)").
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_module_grant('hr');
agent_refuse_agent_caller();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
$managerId = request_integer('manager');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}
if ($managerId === null) {
    render_agent_page($pdo, $id, 'job', ['Choose a manager.']);
}

check_approval($pdo, 'agent_set_manager', 'agent.set_manager',
    'Set manager for ' . $agent['display_name'], ['agent' => $id, 'manager' => $managerId], 'member', $id);

try {
    $after = set_agent_manager($pdo, $id, $managerId);
} catch (RuntimeException $ex) {
    render_agent_page($pdo, $id, 'job', [$ex->getMessage()]);
} catch (PDOException $ex) {
    error_log('agent set manager failed: ' . $ex->getMessage());
    render_agent_page($pdo, $id, 'job', [db_message($ex, 'The manager could not be set.')]);
}
if ($after === []) {
    render_agent_page($pdo, $id, 'job', ['The manager could not be set.']);
}

log_activity($pdo, 'agent.set_manager', 'member', $id, [
    'before' => ['manager_member_id' => $agent['manager_member_id']],
    'after' => ['manager_member_id' => $after['manager_member_id']],
]);
emit_action_status(true, ['did' => 'Set manager for ' . $after['display_name'], 'refresh' => 'agentChanged']);
hx_trigger('agentChanged');
render_agent_page($pdo, $id, 'job');
