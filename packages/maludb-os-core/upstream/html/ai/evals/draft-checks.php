<?php
declare(strict_types=1);

/**
 * Action `eval_case_draft_checks` — log `eval_case.draft_checks`. Gate: mod:evals, humans only. A DRAFT
 * of JEV checks from a rubric (the case's own, or `rubric` as sent): one yes/no check per line — one
 * atomic property per question, as TypeSafe advises. Saves nothing: a person edits the draft and saves
 * it with eval_case_save. No model is asked (db/144; docs/build-specs/eval-jev-grader.md).
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';

require_post();
verify_csrf();

$pdo = db();
aiops_require_evals($pdo);
$caseId = request_integer('eval_case');
$rubric = trim((string) ($_POST['rubric'] ?? ''));
if ($rubric === '' && $caseId !== null) {
    $case = find_eval_case($pdo, $caseId);
    if ($case === null) { aiops_refuse(['Eval case not found.'], 404); }
    $rubric = trim((string) ($case['rubric'] ?? ''));
}
if ($rubric === '') { aiops_refuse(['Give a rubric to draft checks from — one property per line.']); }
$checks = eval_jev_draft_checks($rubric);
if ($checks === []) { aiops_refuse(['No line of that rubric reads as a property to check.']); }
log_activity($pdo, 'eval_case.draft_checks', 'eval_case', $caseId, ['after' => ['checks' => count($checks)]]);
emit_action_status(true, ['did' => 'Drafted ' . count($checks) . ' checks — review and save them']);
respond_saved(['did' => 'Drafted ' . count($checks) . ' checks — review and save them', 'checks' => $checks]);
