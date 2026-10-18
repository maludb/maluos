<?php
declare(strict_types=1);

/**
 * The agent runner's completion callback — not an action, not reachable from a browser session.
 * The runner has no PHP write path and no activity_log grant, so the record that a run ended is
 * written here. It authenticates with RUNNER_KEY (a machine caller has no session, so no CSRF
 * token to present) and only from localhost. The run's figures are re-read from agent_runs —
 * what the caller posts is a hint, never the record.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_post();
$presented = (string) ($_SERVER['HTTP_X_RUNNER_KEY'] ?? '');
if (!in_array($_SERVER['REMOTE_ADDR'] ?? '', ['127.0.0.1', '::1'], true)
    || $presented === '' || !hash_equals(runner_key(), $presented)) {
    http_response_code(403);
    exit('Forbidden.');
}

$pdo = db();
$runId = request_integer('agent_run');
$run = $runId !== null ? find_agent_run($pdo, $runId) : null;
if ($run === null || $run['status'] === 'running') {
    http_response_code(409);
    exit('No finished run by that id.');
}

log_activity($pdo, 'agent_run.finish', 'member', $run['agent_member_id'] !== null ? (int) $run['agent_member_id'] : null, [
    'actor_member_id' => $run['agent_member_id'] !== null ? (int) $run['agent_member_id'] : null,
    'source' => 'agent',
    'agent_run_id' => (int) $run['id'],      // the run's own trail: same ids as every action it took
    'request_id' => (string) $run['request_id'],
    'after' => [
        'run_id' => (int) $run['id'], 'status' => $run['status'], 'trigger' => $run['trigger'],
        'cost' => $run['cost'], 'currency' => $run['currency'],
        'input_tokens' => (int) $run['input_tokens'], 'output_tokens' => (int) $run['output_tokens'],
        'request_id' => $run['request_id'],
    ],
]);
header('Content-Type: application/json');
echo json_encode(['ok' => true]);
