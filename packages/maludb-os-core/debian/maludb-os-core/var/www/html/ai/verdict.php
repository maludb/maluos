<?php
declare(strict_types=1);

/**
 * Action `run_verdict_set` — say whether one agent run, or one assistant answer, was any good.
 * Log: `run_verdict.set`. Gate: whoever may see the thing being judged, and never an agent —
 * marking your own homework is not evidence, and db/124's trigger refuses it regardless.
 *
 * The subject is `run` (an agent_runs id) or `call` (a prompt_ledger id), exactly one. A person
 * has one verdict per subject; saying it again changes it.
 *
 * Born after the cut-over, so it has no template and says its own refusals.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 2) . '/app/features/aiops/request.php';

require_insider();
require_post();
verify_csrf();

if (is_agent_member()) {
    $words = ['A verdict is a person\'s judgement of an agent\'s work; an agent may not give one.'];
    emit_action_status(false, ['errors' => $words]);
    json_error('forbidden', $words[0], 403, ['errors' => $words]);
}

$pdo = db();
$runId = request_integer('run');
$callId = request_integer('call');
$verdict = strtolower(trim(request_string('verdict')));
$note = trim(request_string('note')) ?: null;

$errors = [];
if (($runId === null) === ($callId === null)) {
    $errors[] = 'Say what is being judged: a run, or one model call — one of the two.';
}
if (!in_array($verdict, ['good', 'bad'], true)) {
    $errors[] = 'A verdict is "good" or "bad".';
}
if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);
}

// The subject must be one this caller may see — mcp_agent_runs and mcp_ledger_calls already
// decide that, so a 404 from them is the answer rather than a rule re-implemented here.
$subject = $runId !== null ? find_ops_run($pdo, $runId) : find_ledger_call($pdo, $callId);
if ($subject === null) {
    $words = [$runId !== null ? 'No run with that id that you can see.' : 'No model call with that id that you can see.'];
    emit_action_status(false, ['errors' => $words]);
    json_error('not_found', $words[0], 404, ['errors' => $words]);
}

try {
    [$verdictId, $what] = set_run_verdict($pdo, $runId, $callId, $verdict, $note);
} catch (PDOException $ex) {
    error_log('run verdict failed: ' . $ex->getMessage());
    $words = [db_message($ex, 'The verdict could not be recorded.')];
    emit_action_status(false, ['errors' => $words]);
    respond_invalid($words);
}

$of = $runId !== null ? 'run #' . $runId : 'model call #' . $callId;
log_activity($pdo, 'run_verdict.set', $runId !== null ? 'agent_run' : 'prompt_ledger',
    $runId ?? $callId, ['after' => ['verdict' => $verdict, 'note' => $note, 'was' => $what]]);
emit_action_status(true, [
    'did' => $what === 'changed'
        ? 'Changed your verdict on ' . $of . ' to ' . $verdict
        : 'Marked ' . $of . ' ' . $verdict,
    'refresh' => 'verdictChanged',
    'run_verdict_id' => $verdictId,
]);
