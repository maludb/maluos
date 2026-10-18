<?php
declare(strict_types=1);

/** Screen `eval-schedule-add` — put a set on a standing schedule (param: eval_set). mod:evals. Saved and listed; nothing executes it until the runner exists. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';

$pdo = db();
aiops_require_evals($pdo);
$set = ($sid = request_integer('eval_set')) !== null ? find_eval_set($pdo, $sid) : null;
if ($set === null) { http_response_code(404); exit('Eval set not found.'); }
log_screen_view($pdo, 'eval-schedule-add');
$named = static fn (array $l): array => array_map(static fn (string $k, string $v): array => ['id' => $k, 'name' => $v], array_keys($l), $l);
respond_screen(['set' => present_eval_set($set), 'schedules' => array_map('present_eval_schedule', find_eval_schedules($pdo, (int) $set['eval_set_id'])),
    'runner_built' => false, 'options' => ['kinds' => $named(EVAL_SCHEDULE_KINDS), 'cadences' => $named(EVAL_CADENCES)]]);
