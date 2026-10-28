<?php
declare(strict_types=1);

/** Screen `agent-run-view` — one agent run: what it was asked, what it answered, its calls, what it did, what it cost. Visible through mcp_agent_runs, else 404. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';

require_insider();

$pdo = db();
$id = request_integer('id');
if ($id === null || ($run = find_ops_run($pdo, $id)) === null) {
    http_response_code(404);
    exit('Run not found.');
}
log_screen_view($pdo, 'agent-run-view');
[$calls] = find_ledger_calls($pdo, ['run' => $id, 'period' => 'all'], 1);
respond_screen([
    'run' => present_ops_run($run),
    'calls' => array_map('present_ledger_call', $calls),
    'children' => array_map(static fn (array $c): array => ['id' => (int) $c['agent_run_id'], 'agent_name' => $c['agent_name'] ?? null,
        'agent_member_id' => isset($c['agent_member_id']) ? (int) $c['agent_member_id'] : null, 'status' => (string) $c['status'],
        'cost' => (string) $c['cost'], 'currency' => (string) $c['currency'], 'started_at' => json_ts($c['started_at'])], find_ops_child_runs($pdo, $id)),
    'actions' => array_map(static fn (array $a): array => ['id' => (int) $a['id'], 'action' => (string) $a['action'], 'entity_type' => $a['entity_type'],
        'entity_id' => $a['entity_id'] !== null ? (int) $a['entity_id'] : null, 'occurred_at' => json_ts($a['occurred_at'])], find_ops_run_actions($pdo, $id)),
    'events' => array_map('present_run_event', find_run_events($pdo, $id)),
    'verdicts' => present_verdicts(find_my_verdict($pdo, $id, null), find_verdicts($pdo, $id, null)),
    'can' => ['promote' => !is_agent_member() && (has_module_grant('evals') || aiops_can_see_agent($pdo, (int) $run['agent_member_id'])),
              // Anyone who can open the run can say what they thought of it; an agent never can.
              'verdict' => !is_agent_member()],
]);
