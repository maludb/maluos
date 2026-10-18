<?php
declare(strict_types=1);

/**
 * Action `agent_offboard` — log `agent.offboard`. Gate: super. Revokes tokens and grants;
 * the trail (hr_events, activity_log) is kept — an agent row is never deleted.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
$reason = request_string('reason');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}
if ($reason === '') {
    render_agent_page($pdo, $id, 'job', ['Offboarding needs a reason.']);
}

check_approval($pdo, 'agent_offboard', 'agent.offboard', 'Offboard ' . $agent['display_name'],
    ['agent' => $id, 'reason' => $reason], 'member', $id);

$after = offboard_agent($pdo, $id, $reason, (int) current_member_id());
if ($after === []) {
    render_agent_page($pdo, $id, 'job', ['This agent is already offboarded.']);
}

log_activity($pdo, 'agent.offboard', 'member', $id, [
    'before' => ['status' => $agent['status']], 'after' => ['status' => $after['status'], 'reason' => $reason],
]);
emit_action_status(true, ['did' => 'Offboarded ' . $after['display_name'], 'refresh' => 'agentChanged']);
hx_trigger('agentChanged');
render_agent_page($pdo, $id, 'job');
