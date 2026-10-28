<?php
declare(strict_types=1);

/** Action `eval_case_set_active` — switch a case on or off (an inactive case is kept, and skipped by a run). mod:evals; never an agent. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';

require_post();
verify_csrf();

$pdo = db();
aiops_require_evals($pdo);
$case = ($id = request_integer('eval_case')) !== null ? find_eval_case($pdo, $id) : null;
if ($case === null) { aiops_refuse(['Eval case not found.'], 404); }
if (!array_key_exists('active', $_POST)) { aiops_refuse(['Say whether the case is active: 1 or 0.']); }
$active = request_bool('active');
$pdo->prepare('UPDATE eval_cases SET active = :a, updated_at = now() WHERE id = :id')->execute(['a' => $active ? 'true' : 'false', 'id' => $id]);
log_activity($pdo, 'eval_case.set_active', 'eval_case', $id, ['before' => ['active' => (bool) $case['active']], 'after' => ['active' => $active]]);
emit_action_status(true, ['did' => ($active ? 'Switched on case ' : 'Switched off case ') . $case['title'], 'refresh' => 'aiopsChanged']);
header('HX-Push-Url: /ai/evals/' . (int) $case['eval_set_id']);
