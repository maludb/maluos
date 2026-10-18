<?php
declare(strict_types=1);

/**
 * Action `agent_run_duty_now` — run one of the agent's duties now, outside its schedule.
 * Until the agent runtime existed this endpoint answered "nothing was run" rather than pretend;
 * it now asks the runner (app/features/agents/runs.php), with the duty's own instructions.
 * Gate: agent's manager, mod:hr (OR).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
$dutyId = request_integer('duty');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}
agent_require_hr_or_manager($pdo, $agent);
agent_refuse_agent_caller();

$duty = $dutyId !== null ? find_agent_duty($pdo, $dutyId) : null;
if ($duty === null || (int) $duty['agent_member_id'] !== $id) {
    render_agent_page($pdo, $id, 'duties', ['That duty does not belong to this agent.']);
}

[$run, $error] = start_agent_run($id, (string) $duty['instructions'], 'duty', (int) $duty['id'], (int) $_SESSION['member_id']);
if ($error !== null) {
    emit_action_status(false, ['errors' => [$error]]);
    render_agent_page($pdo, $id, 'duties', [$error]);
}

log_activity($pdo, 'agent_run.start', 'member', $id, [
    'after' => ['trigger' => 'duty', 'duty' => $duty['name'], 'run_id' => (int) $run['run_id'], 'request_id' => $run['request_id']],
]);
$did = 'Started "' . $duty['name'] . '" for ' . $agent['display_name'] . ' — run #' . (int) $run['run_id'];
emit_action_status(true, ['did' => $did, 'run_id' => (int) $run['run_id'], 'refresh' => 'agentChanged']);
render_agent_page($pdo, $id, 'duties');
