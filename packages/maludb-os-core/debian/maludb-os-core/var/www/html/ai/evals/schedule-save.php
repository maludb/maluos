<?php
declare(strict_types=1);

/**
 * Action `eval_schedule_save` — put a set on a standing schedule, or change one. mod:evals; never an agent. **Saved and listed only:**
 * nothing executes a schedule until the eval runner exists, so next_run_at stays empty and the answer says so.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';

require_post();
verify_csrf();

$pdo = db();
aiops_require_evals($pdo);
$set = aiops_eval_set($pdo);
$scheduleId = request_integer('schedule');
$kind = request_string('kind');
$cadence = request_string('cadence');
$sample = request_integer('sample_size');
$delta = array_key_exists('regression_delta', $_POST) ? request_string('regression_delta') : '5';
$errors = [];
if (!isset(EVAL_SCHEDULE_KINDS[$kind])) { $errors[] = 'A schedule is a scheduled_run or trace_sampling.'; }
if (!isset(EVAL_CADENCES[$cadence])) { $errors[] = 'Cadence is daily, weekly or monthly.'; }
if ($kind === 'trace_sampling' && ($sample === null || $sample < 1 || $sample > 1000)) { $errors[] = 'Trace sampling needs a sample size from 1 to 1000.'; }
if ($kind === 'scheduled_run' && $sample !== null && $sample < 1) { $errors[] = 'A sample size is above zero.'; }
if (!is_numeric($delta) || (float) $delta < 0 || (float) $delta > 100) { $errors[] = 'The regression delta is a number of points from 0 to 100.'; }
if ($errors !== []) { aiops_refuse($errors); }
$active = !array_key_exists('active', $_POST) || request_bool('active');
$args = ['k' => $kind, 'c' => $cadence, 'n' => $sample, 'd' => $delta, 'a' => $active ? 'true' : 'false'];
if ($scheduleId === null) {
    $st = $pdo->prepare('INSERT INTO eval_schedules (eval_set_id, kind, cadence, sample_size, regression_delta, active, created_by) VALUES (:s, :k, :c, :n, :d, :a, :by) RETURNING id');
    $st->execute($args + ['s' => (int) $set['eval_set_id'], 'by' => (int) current_member_id()]);
    $scheduleId = (int) $st->fetchColumn();
    $before = null;
} else {
    $b = $pdo->prepare('SELECT kind, cadence, sample_size, regression_delta, active FROM eval_schedules WHERE id = :id AND eval_set_id = :s');
    $b->execute(['id' => $scheduleId, 's' => (int) $set['eval_set_id']]);
    if (($before = $b->fetch() ?: null) === null) { aiops_refuse(['Schedule not found on that set.'], 404); }
    $pdo->prepare('UPDATE eval_schedules SET kind = :k, cadence = :c, sample_size = :n, regression_delta = :d, active = :a, updated_at = now() WHERE id = :id')->execute($args + ['id' => $scheduleId]);
}
log_activity($pdo, 'eval_schedule.save', 'eval_schedule', $scheduleId, ['before' => $before, 'after' => ['eval_set_id' => (int) $set['eval_set_id'], 'kind' => $kind, 'cadence' => $cadence, 'sample_size' => $sample, 'regression_delta' => $delta, 'active' => $active]]);
emit_action_status(true, ['did' => 'Saved the ' . mb_strtolower(EVAL_CADENCES[$cadence]) . ' schedule for ' . $set['name'] . ' — the Auditor runs it when it falls due', 'refresh' => 'aiopsChanged']);
header('HX-Push-Url: /ai/evals/' . (int) $set['eval_set_id']);
