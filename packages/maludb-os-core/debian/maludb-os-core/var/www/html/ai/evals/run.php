<?php
declare(strict_types=1);

/**
 * Action `eval_run_start` — run an eval set against an agent, on demand. Gate: mod:evals or the
 * agent's manager; never an agent. Log: `eval_run.start`.
 *
 * Evals ADVISE (owner, 2026-09-20): nothing waits on this and nothing is gated by its answer.
 * The runner works the run in the background and this returns as soon as it has been accepted,
 * because three trials per case takes minutes.
 *
 * An eval run cannot change anything: under an evaluation the actions MCP server records a write
 * and never sends it (mcp/actions_server.py). That is what makes this safe to press.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';

require_post();
verify_csrf();

$pdo = db();
$agentOfSet = null;
if (($sid = request_integer('eval_set')) !== null) {
    $b = $pdo->prepare('SELECT agent_member_id FROM eval_sets WHERE id = :id');
    $b->execute(['id' => $sid]);
    $agentOfSet = ($v = $b->fetchColumn()) !== false && $v !== null ? (int) $v : null;
}
aiops_require_evals($pdo, $agentOfSet, true, true);

if (is_agent_member()) {
    // The Auditor (scheduled evals, owner 2026-09-27): an agent sees no eval set through the people's views, so
    // the set is read here from the table — its grant for eval_run_start was checked at the Actions MCP.
    $st = $pdo->prepare("SELECT s.id AS eval_set_id, s.name, s.agent_member_id, s.pass_threshold, s.status,
                                (SELECT count(*) FROM eval_cases c WHERE c.eval_set_id = s.id AND c.active) AS active_case_count
                           FROM eval_sets s WHERE s.id = :id");
    $st->execute(['id' => request_integer('eval_set') ?? 0]);
    $set = $st->fetch() ?: null;
    if ($set === null) { aiops_refuse(['Eval set not found.'], 404); }
} else {
    $set = aiops_eval_set($pdo);
}
if ((int) $set['active_case_count'] === 0) {
    aiops_refuse(['The set has no active cases — write one first.'], 409);
}
if ($set['status'] === 'retired') {
    aiops_refuse(['That set is retired. Make it active again before running it.'], 409);
}

$trigger = request_string('trigger') ?: (is_agent_member() ? 'continuous' : 'manual');
if (is_agent_member() ? $trigger !== 'continuous' : !in_array($trigger, ['manual', 'change_control', 'hiring'], true)) {
    aiops_refuse([is_agent_member() ? 'The Auditor starts a run as continuous — a scheduled evaluation.'
                                    : 'A run is started by a person: manual, change_control or hiring.']);
}

[$evalRunId, $error] = start_eval_run($pdo, $set, request_integer('agent'), request_integer('config_version'), $trigger);

if ($evalRunId === null) {
    aiops_refuse([$error ?? 'The evaluation could not be started.'], 409);
}

log_activity($pdo, 'eval_run.start', 'eval_set', (int) $set['eval_set_id'], [
    'after' => ['eval_run_id' => $evalRunId, 'trigger' => $trigger, 'started' => $error === null,
                'cases' => (int) $set['active_case_count'], 'error' => $error],
]);

if ($error !== null) {
    aiops_refuse([$error . ' The run is recorded as an error at /ai/evals/runs/' . $evalRunId . '.'], 502);
}

emit_action_status(true, [
    'did' => 'Started an evaluation of "' . $set['name'] . '" — ' . (int) $set['active_case_count']
        . ' case(s), three trials each. It advises; nothing is waiting on it.',
    'refresh' => 'aiopsChanged',
    'eval_run_id' => $evalRunId,
]);
header('HX-Push-Url: /ai/evals/runs/' . $evalRunId);
