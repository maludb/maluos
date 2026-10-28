<?php
declare(strict_types=1);

/**
 * Action `eval_case_promote_trace` — turn a REAL call (ledger_entry) or run (agent_run) into a case of a set: the input is what
 * the model was actually given, the expected answer what it actually said, the source kept on the case. mod:evals or the agent's
 * manager; never an agent. Only a trace the caller can read: the payload through mcp_prompt_payloads, the run through mcp_agent_runs.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';

require_post();
verify_csrf();

$pdo = db();
$set = null;
if (($sid = request_integer('eval_set')) !== null) {
    $b = $pdo->prepare('SELECT agent_member_id FROM eval_sets WHERE id = :id');
    $b->execute(['id' => $sid]);
    $agentOfSet = $b->fetchColumn();
    aiops_require_evals($pdo, $agentOfSet !== false && $agentOfSet !== null ? (int) $agentOfSet : null, true);
    $set = find_eval_set($pdo, $sid);
} else {
    aiops_require_evals($pdo);
}
if ($set === null) { aiops_refuse(['Eval set not found.'], 404); }
$ledgerId = request_integer('ledger_entry');
$runId = request_integer('agent_run');
if (($ledgerId === null) === ($runId === null)) { aiops_refuse(['Name one trace to promote: a ledger_entry or an agent_run.']); }
if ($ledgerId !== null) {
    $call = find_ledger_call($pdo, $ledgerId);
    $payload = $call !== null ? find_ledger_payload($pdo, $ledgerId) : null;
    if ($call === null) { aiops_refuse(['That call does not exist, or you cannot see it.'], 404); }
    if ($payload === null || $payload['context'] === null || $payload['archived_at'] !== null) { aiops_refuse(['That call\'s prompt is no longer stored (or is not yours to read), so there is nothing to make a case from.'], 409); }
    [$input, $expected, $default] = [(string) $payload['context'], $payload['response'] !== null ? (string) $payload['response'] : null, 'From call #' . $ledgerId];
} else {
    $run = find_ops_run($pdo, $runId);
    if ($run === null) { aiops_refuse(['That run does not exist, or you cannot see it.'], 404); }
    if (trim((string) ($run['instructions'] ?? '')) === '') { aiops_refuse(['That run has no instructions recorded, so there is nothing to make a case from.'], 409); }
    [$input, $expected, $default] = [eval_text_to_json((string) $run['instructions']), trim((string) ($run['result'] ?? '')) !== '' ? eval_text_to_json((string) $run['result']) : null, 'From run #' . $runId];
}
$title = mb_substr(trim(request_string('title')), 0, 200) ?: $default;
$rubric = mb_substr(trim((string) ($_POST['rubric'] ?? '')), 0, 8000) ?: null;
$st = $pdo->prepare("INSERT INTO eval_cases (eval_set_id, title, input, expected, rubric, grader, origin, source_ledger_id, source_run_id, promoted_by)
                       VALUES (:s, :t, :i::jsonb, :e::jsonb, :r, 'rubric_llm', 'promoted_trace', :l, :run, :by) RETURNING id");
$st->execute(['s' => (int) $set['eval_set_id'], 't' => $title, 'i' => $input, 'e' => $expected, 'r' => $rubric, 'l' => $ledgerId, 'run' => $runId, 'by' => (int) current_member_id()]);
$caseId = (int) $st->fetchColumn();
log_activity($pdo, 'eval_case.promote', 'eval_case', $caseId, ['after' => ['eval_set_id' => (int) $set['eval_set_id'], 'title' => $title, 'source_ledger_id' => $ledgerId, 'source_run_id' => $runId]]);
emit_action_status(true, ['did' => 'Made case “' . $title . '” from the ' . ($ledgerId !== null ? 'call' : 'run'), 'refresh' => 'aiopsChanged']);
header('HX-Push-Url: /ai/evals/cases/' . $caseId . '/edit');
