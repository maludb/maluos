<?php
declare(strict_types=1);

/**
 * Screens `eval-case-add` (params: eval_set, from_ledger, from_run) and `eval-case-edit`. mod:evals.
 * from_ledger / from_run prefill the title and input from a real call or run THE CALLER CAN READ —
 * the payload comes through mcp_prompt_payloads, the run through mcp_agent_runs.
 */
require_once dirname(__DIR__, 4) . '/app/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 4) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 4) . '/app/features/aiops/present.php';

$pdo = db();
aiops_require_evals($pdo);
$id = request_integer('id');
$named = static fn (array $l): array => array_map(static fn (string $k, string $v): array => ['id' => $k, 'name' => $v], array_keys($l), $l);
if ($id !== null) {
    if (($case = find_eval_case($pdo, $id)) === null) { http_response_code(404); exit('Eval case not found.'); }
    $set = find_eval_set($pdo, (int) $case['eval_set_id']);
    log_screen_view($pdo, 'eval-case-edit');
    respond_screen(['case' => present_eval_case($case), 'set' => present_eval_set($set ?? []), 'from' => null, 'options' => ['graders' => $named(EVAL_GRADERS)]]);
}
$set = ($sid = request_integer('eval_set')) !== null ? find_eval_set($pdo, $sid) : null;
if ($set === null) { http_response_code(404); exit('Eval set not found.'); }
$prefill = ['eval_set_id' => (int) $set['eval_set_id'], 'grader' => 'rubric_llm', 'weight' => '1'];
$from = null;
if (($ledgerId = request_integer('from_ledger')) !== null && ($call = find_ledger_call($pdo, $ledgerId)) !== null) {
    $payload = find_ledger_payload($pdo, $ledgerId);
    $prefill += ['title' => 'From call #' . $ledgerId, 'input' => $payload !== null && $payload['context'] !== null ? $payload['context'] : json_encode(['text' => '']),
                 'expected' => $payload['response'] ?? null, 'origin' => 'promoted_trace', 'source_ledger_id' => $ledgerId];
    $from = ['kind' => 'ledger', 'id' => $ledgerId];
} elseif (($runId = request_integer('from_run')) !== null && ($run = find_ops_run($pdo, $runId)) !== null) {
    $prefill += ['title' => 'From run #' . $runId, 'input' => json_encode(['text' => (string) ($run['instructions'] ?? '')]), 'expected' => json_encode(['text' => (string) ($run['result'] ?? '')]),
                 'origin' => 'promoted_trace', 'source_run_id' => $runId];
    $from = ['kind' => 'run', 'id' => $runId];
}
// A case written here is graded by JEV by default (db/144); one made from a trace keeps the rubric
// judge, since promoting it saves no checks.
if ($from === null) { $prefill['grader'] = 'jev'; }
log_screen_view($pdo, 'eval-case-add');
respond_screen(['case' => present_eval_case($prefill), 'set' => present_eval_set($set), 'from' => $from, 'options' => ['graders' => $named(EVAL_GRADERS)]]);
