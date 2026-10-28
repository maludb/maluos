<?php
declare(strict_types=1);

/**
 * Screen `eval-run-view` — one eval run's per-case results.
 *
 * The score counts only what has been GRADED (owner, 2026-09-20), so the screen says what it
 * covers: how many cases were graded, how many await a person, and — against the run's baseline —
 * which cases CHANGED. A score moving from 82 to 79 tells a reader nothing about what broke.
 */
require_once dirname(__DIR__, 4) . '/app/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 4) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 4) . '/app/features/aiops/present.php';

require_insider();
if (is_agent_member()) { deny('Evals are people\'s work — an agent cannot open them.'); }

$pdo = db();
$st = $pdo->prepare('SELECT r.*, ' . eval_run_names_sql() . ' FROM mcp_eval_runs r WHERE r.eval_run_id = :id');
$st->execute(['id' => request_integer('id') ?? 0]);
if (($run = $st->fetch()) === false) { http_response_code(404); exit('Eval run not found.'); }
log_screen_view($pdo, 'eval-run-view');
$res = $pdo->prepare('SELECT * FROM mcp_eval_results WHERE eval_run_id = :id ORDER BY eval_result_id');
$res->execute(['id' => (int) $run['eval_run_id']]);
$rows = $res->fetchAll();

// What changed since the baseline, case by case. Null when there is no baseline to compare with.
$changed = [];
if ($run['baseline_run_id'] !== null) {
    $diff = $pdo->prepare(<<<'SQL'
        SELECT n.eval_case_id, b.passed AS was, n.passed AS now_passed
          FROM mcp_eval_results n
          LEFT JOIN mcp_eval_results b ON b.eval_case_id = n.eval_case_id AND b.eval_run_id = :base
         WHERE n.eval_run_id = :id AND b.passed IS DISTINCT FROM n.passed
    SQL);
    $diff->execute(['id' => (int) $run['eval_run_id'], 'base' => (int) $run['baseline_run_id']]);
    foreach ($diff->fetchAll() as $d) {
        $changed[(int) $d['eval_case_id']] = $d['was'] === null ? 'new' : ((bool) $d['now_passed'] ? 'fixed' : 'regressed');
    }
}
$awaiting = count(array_filter($rows, static fn (array $r): bool => !$r['is_graded']));

respond_screen([
    'run' => present_eval_run($run),
    'results' => array_map(static fn (array $r): array => ['id' => (int) $r['eval_result_id'], 'case_id' => (int) $r['eval_case_id'],
        'case_title' => (string) $r['case_title'], 'agent_run_id' => $r['agent_run_id'] !== null ? (int) $r['agent_run_id'] : null,
        'passed' => (bool) $r['passed'], 'score' => $r['score'] !== null ? (string) $r['score'] : null,
        'grader_notes' => $r['grader_notes'] ?? null, 'grader' => (string) $r['grader'],
        'is_graded' => (bool) $r['is_graded'], 'change' => $changed[(int) $r['eval_case_id']] ?? null,
        'awaiting_person' => !empty($r['awaiting_person']) && $r['graded_by'] === null,
        'graded_by_person' => $r['graded_by'] !== null,
        'jev' => present_eval_jev_detail($r['grader_detail'] ?? null)], $rows),
    'coverage' => [
        'graded' => count($rows) - $awaiting,
        'awaiting' => $awaiting,
        'total' => (int) $run['cases_total'],
        // The sentence a reader needs beside the number, not buried in a tooltip.
        'note' => $awaiting > 0
            ? $awaiting . ' case(s) await a person\'s grade and are NOT in this score — grading them will change it.'
            : 'Every case that ran has been graded.',
    ],
    'can' => ['grade' => has_module_grant('evals')],
]);
