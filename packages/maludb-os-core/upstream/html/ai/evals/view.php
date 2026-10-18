<?php
declare(strict_types=1);

/** Screen `eval-set-view` — one set: its cases, its schedules, its runs. There is no runner yet, and the page says so. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';

require_insider();
if (is_agent_member()) { deny('Evals are people\'s work — an agent cannot open them.'); }

$pdo = db();
$id = request_integer('id');
if ($id === null || ($set = find_eval_set($pdo, $id)) === null) {
    http_response_code(404);
    exit('Eval set not found.');
}
log_screen_view($pdo, 'eval-set-view');
$manager = aiops_can_see_agent($pdo, $set['agent_member_id'] !== null ? (int) $set['agent_member_id'] : null);
respond_screen([
    'set' => present_eval_set($set),
    'cases' => array_map('present_eval_case', find_eval_cases($pdo, $id)),
    'schedules' => array_map('present_eval_schedule', find_eval_schedules($pdo, $id)),
    'runs' => array_map('present_eval_run', find_eval_runs($pdo, $id)),
    // How each JEV check has answered, and how often a person agreed (db/144).
    'calibration' => (static function () use ($pdo, $id): array {
        $st = $pdo->prepare('SELECT * FROM mcp_eval_check_calibration WHERE eval_set_id = :id ORDER BY check_id');
        $st->execute(['id' => $id]);
        return array_map('present_eval_calibration', $st->fetchAll());
    })(),
    'runner_built' => true, 'runner_note' => EVAL_RUNNER_NOTE,
    'can' => ['write' => has_module_grant('evals'), 'run' => has_module_grant('evals') || $manager],
]);
