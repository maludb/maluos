<?php
declare(strict_types=1);

/**
 * Action `agent_run_cancel` — stop a running agent. Gate: the agent's manager, mod:hr (OR).
 * The runner stops the harness process; the run ends `cancelled` and the callback logs it.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_post();
verify_csrf();

$pdo = db();
$runId = request_integer('agent_run');
$run = $runId !== null ? find_agent_run($pdo, $runId) : null;
if ($run === null || $run['agent_member_id'] === null || ($agent = find_agent($pdo, (int) $run['agent_member_id'])) === null) {
    http_response_code(404);
    exit('Run not found.');
}
$id = (int) $agent['agent_member_id'];
agent_require_hr_or_manager($pdo, $agent);
agent_refuse_agent_caller();

$error = $run['status'] !== 'running' ? 'That run is not running.' : cancel_agent_run((int) $run['id']);
if ($error !== null) {
    emit_action_status(false, ['errors' => [$error]]);
    render_agent_page($pdo, $id, 'duties', [$error]);
}

log_activity($pdo, 'agent_run.cancel', 'member', $id, ['after' => ['run_id' => (int) $run['id']]]);
$did = 'Cancelling run #' . (int) $run['id'] . ' for ' . $agent['display_name'];
emit_action_status(true, ['did' => $did, 'refresh' => 'agentChanged']);
render_agent_page($pdo, $id, 'duties');
