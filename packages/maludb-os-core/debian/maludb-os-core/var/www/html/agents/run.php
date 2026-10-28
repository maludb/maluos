<?php
declare(strict_types=1);

/**
 * Action `agent_run_start` — ask the agent to do one piece of work now. Gate: the agent's
 * manager, mod:hr (OR); never an agent (delegation is its own action, agent_delegate).
 * PHP only asks: the runner creates the agent_runs row, runs the harness and calls back
 * (run-callback.php) when it ends. The answer here is "started", not "done".
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}
agent_require_hr_or_manager($pdo, $agent);
agent_refuse_agent_caller();

$instructions = trim(request_string('instructions'));
$errors = [];
if ($instructions === '') {
    $errors[] = 'Say what the agent should do.';
} elseif (strlen($instructions) > AGENT_RUN_INSTRUCTIONS_MAX) {
    $errors[] = 'The instructions are too long.';
}
if ($errors === []) {
    [$run, $error] = start_agent_run($id, $instructions, 'manual', null, (int) $_SESSION['member_id']);
    if ($error !== null) {
        $errors[] = $error;
    }
}
if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    render_agent_page($pdo, $id, 'duties', $errors);
}

log_activity($pdo, 'agent_run.start', 'member', $id, [
    'after' => ['trigger' => 'manual', 'run_id' => (int) $run['run_id'], 'request_id' => $run['request_id']],
]);
$did = 'Started run #' . (int) $run['run_id'] . ' for ' . $agent['display_name'];
emit_action_status(true, ['did' => $did, 'run_id' => (int) $run['run_id'], 'refresh' => 'agentChanged']);
render_agent_page($pdo, $id, 'duties');
