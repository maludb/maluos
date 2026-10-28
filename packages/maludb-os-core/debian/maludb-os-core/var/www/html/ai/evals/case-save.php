<?php
declare(strict_types=1);

/**
 * Action `eval_case_save` — write or change a case: what the agent is given (input), what a good answer is (expected and / or a
 * rubric), and how it is graded. mod:evals; never an agent. The case's TEXT is not logged — a case may quote a real prompt.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';

require_post();
verify_csrf();

$pdo = db();
aiops_require_evals($pdo);
$caseId = request_integer('eval_case');
$existing = null;
if ($caseId !== null && ($existing = find_eval_case($pdo, $caseId)) === null) { aiops_refuse(['Eval case not found.'], 404); }
$set = $existing !== null ? find_eval_set($pdo, (int) $existing['eval_set_id']) : aiops_eval_set($pdo);
if ($set === null) { aiops_refuse(['Eval set not found.'], 404); }
$has = static fn (string $k): bool => array_key_exists($k, $_POST);
$title = mb_substr(trim(request_string('title')), 0, 200);
$input = (string) ($_POST['input'] ?? '');
$expected = $has('expected') ? (string) $_POST['expected'] : null;
$rubric = $has('rubric') || $existing === null ? (mb_substr(trim((string) ($_POST['rubric'] ?? '')), 0, 8000) ?: null) : $existing['rubric'];
$grader = $has('grader') ? request_string('grader') : (string) ($existing['grader'] ?? 'rubric_llm');
$weight = $has('weight') ? request_string('weight') : (string) ($existing['weight'] ?? '1');
$errors = [];
if ($title === '') { $errors[] = 'Give the case a title.'; }
if (trim($input) === '') { $errors[] = 'Say what the agent is given — the input.'; }
if (strlen($input) > 200000 || strlen((string) $expected) > 200000) { $errors[] = 'A case\'s input and expected answer are at most 200 KB each.'; }
if (!isset(EVAL_GRADERS[$grader])) { $errors[] = 'A case is graded by jev, rubric_llm, exact, programmatic or human.'; }
if (!is_numeric($weight) || (float) $weight <= 0 || (float) $weight > 100) { $errors[] = 'Weight is a number above 0 (1 is normal).'; }
$expectedJson = $expected !== null ? (trim($expected) === '' ? null : eval_text_to_json($expected)) : ($existing['expected'] ?? null);
if ($grader === 'exact' && $expectedJson === null) { $errors[] = 'An exact-match case needs its expected answer.'; }
if ($grader === 'rubric_llm' && $rubric === null && $expectedJson === null) { $errors[] = 'Give a rubric or an expected answer — something has to say what good looks like.'; }
// JEV (db/144): the case's checks, validated to the shape the runner asks JEV.
$checksJson = $existing['checks'] ?? null;
if ($grader === 'jev') {
    if ($has('checks') || $checksJson === null) {
        [$checks, $checkErrors] = eval_jev_checks_from_json((string) ($_POST['checks'] ?? ''));
        $errors = array_merge($errors, $checkErrors);
        $checksJson = $checks !== null ? json_encode($checks, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) : null;
    }
} else {
    $checksJson = $has('checks') && trim((string) $_POST['checks']) === '' ? null : $checksJson;
}
if ($errors !== []) { aiops_refuse($errors); }
if ($caseId === null) {
    $st = $pdo->prepare('INSERT INTO eval_cases (eval_set_id, title, input, expected, rubric, grader, weight, checks) VALUES (:s, :t, :i::jsonb, :e::jsonb, :r, :g, :w, :c::jsonb) RETURNING id');
    $st->execute(['s' => (int) $set['eval_set_id'], 't' => $title, 'i' => eval_text_to_json($input), 'e' => $expectedJson, 'r' => $rubric, 'g' => $grader, 'w' => $weight, 'c' => $checksJson]);
    $caseId = (int) $st->fetchColumn();
} else {
    $pdo->prepare('UPDATE eval_cases SET title = :t, input = :i::jsonb, expected = :e::jsonb, rubric = :r, grader = :g, weight = :w, checks = :c::jsonb, updated_at = now() WHERE id = :id')
        ->execute(['t' => $title, 'i' => eval_text_to_json($input), 'e' => $expectedJson, 'r' => $rubric, 'g' => $grader, 'w' => $weight, 'c' => $checksJson, 'id' => $caseId]);
}
log_activity($pdo, 'eval_case.save', 'eval_case', $caseId, ['after' => ['eval_set_id' => (int) $set['eval_set_id'], 'title' => $title, 'grader' => $grader, 'weight' => $weight, 'new' => $existing === null,
    'checks' => $grader === 'jev' ? count(json_decode((string) $checksJson, true) ?: []) : null]]);
emit_action_status(true, ['did' => ($existing === null ? 'Added case ' : 'Saved case ') . $title, 'refresh' => 'aiopsChanged']);
header('HX-Push-Url: /ai/evals/' . (int) $set['eval_set_id']);
