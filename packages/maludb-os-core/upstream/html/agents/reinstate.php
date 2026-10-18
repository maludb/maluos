<?php
declare(strict_types=1);

/** Action `agent_reinstate` — log `agent.reinstate`. Gate: mod:hr. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_module_grant('hr');
agent_refuse_agent_caller();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}

check_approval($pdo, 'agent_reinstate', 'agent.reinstate', 'Reinstate ' . $agent['display_name'],
    ['agent' => $id], 'member', $id);

$after = reinstate_agent($pdo, $id, (int) current_member_id());
if ($after === []) {
    render_agent_page($pdo, $id, 'job', ['This agent is not suspended.']);
}

log_activity($pdo, 'agent.reinstate', 'member', $id, [
    'before' => ['status' => $agent['status']], 'after' => ['status' => $after['status']],
]);
emit_action_status(true, ['did' => 'Reinstated ' . $after['display_name'], 'refresh' => 'agentChanged']);
hx_trigger('agentChanged');
render_agent_page($pdo, $id, 'job');
