<?php
declare(strict_types=1);

/** Action `eval_result_grade` — a person grades a human-graded case's result, a JEV result JEV was unsure of, or spot-checks a JEV grade. mod:evals, humans only. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';

require_post();
verify_csrf();

$pdo = db();
aiops_require_evals($pdo);
$st = $pdo->prepare('SELECT r.eval_result_id, r.eval_run_id, r.passed, r.score, c.grader FROM mcp_eval_results r JOIN mcp_eval_cases c ON c.eval_case_id = r.eval_case_id WHERE r.eval_result_id = :id');
$st->execute(['id' => request_integer('eval_result') ?? 0]);
if (($result = $st->fetch()) === false) { aiops_refuse(['Eval result not found.'], 404); }
// A person grades a human-graded case, a JEV case JEV was unsure of, or spot-checks any JEV grade —
// JEV's own answers stay in grader_detail, so agreement is measurable (db/144).
if (!in_array($result['grader'], ['human', 'jev'], true)) { aiops_refuse(['Only a human-graded or a JEV-graded case is graded by hand.'], 409); }
if (!array_key_exists('passed', $_POST)) { aiops_refuse(['Say whether it passed: 1 or 0.']); }
$score = request_string('score');
if ($score !== '' && (!is_numeric($score) || (float) $score < 0 || (float) $score > 100)) { aiops_refuse(['A score is from 0 to 100.']); }
$passed = request_bool('passed');
$pdo->prepare('UPDATE eval_results SET passed = :p, score = :s, grader_notes = :n, graded_by = :by WHERE id = :id')
    ->execute(['p' => $passed ? 'true' : 'false', 's' => $score !== '' ? $score : null, 'n' => mb_substr(trim((string) ($_POST['notes'] ?? '')), 0, 4000) ?: null, 'by' => (int) current_member_id(), 'id' => (int) $result['eval_result_id']]);
log_activity($pdo, 'eval_result.grade', 'eval_result', (int) $result['eval_result_id'], ['before' => ['passed' => (bool) $result['passed'], 'score' => $result['score']], 'after' => ['passed' => $passed, 'score' => $score !== '' ? $score : null]]);

// The run's score counts only what has been graded (owner, 2026-09-20), so this grade may be the
// one that finally makes the number whole. It is never restated silently: the change is logged and
// said out loud.
$rescored = eval_run_rescore($pdo, (int) $result['eval_run_id']);
$also = '';
if ($rescored['changed'] ?? false) {
    log_activity($pdo, 'eval_run.rescore', 'eval_run', (int) $result['eval_run_id'], [
        'before' => ['score' => $rescored['old_score'], 'status' => $rescored['old_status']],
        'after' => ['score' => $rescored['score'], 'status' => $rescored['status'], 'awaiting' => $rescored['awaiting']],
    ]);
    $also = ' The run now scores ' . ($rescored['score'] ?? '—') . ' (' . $rescored['status'] . ')'
        . ((int) $rescored['awaiting'] > 0 ? ', with ' . (int) $rescored['awaiting'] . ' still awaiting a grade.' : '.');
}
emit_action_status(true, ['did' => 'Graded the result: ' . ($passed ? 'passed' : 'failed') . $also, 'refresh' => 'aiopsChanged']);
header('HX-Push-Url: /ai/evals/runs/' . (int) $result['eval_run_id']);
