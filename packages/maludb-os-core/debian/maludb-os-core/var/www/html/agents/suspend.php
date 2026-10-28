<?php
declare(strict_types=1);

/** Action `agent_suspend` — log `agent.suspend`. Gate: mod:hr, agent's manager (OR). */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
$reason = request_string('reason') ?: null;
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}
agent_require_hr_or_manager($pdo, $agent);
agent_refuse_agent_caller();

check_approval($pdo, 'agent_suspend', 'agent.suspend', 'Suspend ' . $agent['display_name'],
    ['agent' => $id, 'reason' => $reason], 'member', $id);

$after = suspend_agent($pdo, $id, $reason, (int) current_member_id());
if ($after === []) {
    render_agent_page($pdo, $id, 'job', ['This agent cannot be suspended from its current status.']);
}

log_activity($pdo, 'agent.suspend', 'member', $id, [
    'before' => ['status' => $agent['status']], 'after' => ['status' => $after['status'], 'reason' => $reason],
]);
emit_action_status(true, ['did' => 'Suspended ' . $after['display_name'], 'refresh' => 'agentChanged']);
hx_trigger('agentChanged');
render_agent_page($pdo, $id, 'job');
