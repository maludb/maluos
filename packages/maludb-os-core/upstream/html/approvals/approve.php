<?php
declare(strict_types=1);

/**
 * Action `approval_approve` — approve a paused action AND run it. Gate: the request's approver.
 * pending -> approved, then the stored request is replayed through its own handler as the
 * requester (features/approvals/replay.php) -> executed | execution_failed. An approval is never
 * silently "done": the answer says which.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/approvals/decide.php';

require_post();
verify_csrf();
[$pdo, $request] = approvals_open_request();

if ((int) $request['approver_member_id'] !== current_member_id()) {
    deny('Only ' . $request['approver_name'] . ' can decide this request.');
}
if ($request['status'] !== 'pending') {
    approvals_fail('That request is ' . $request['status'] . ' — it can no longer be approved.', 409);
}
$note = trim(request_string('note')) ?: null;
if (!decide_approval_request($pdo, (int) $request['id'], 'approved', (int) current_member_id(), $note)) {
    approvals_fail('That request was decided by someone else a moment ago.', 409);
}
log_activity($pdo, 'approval_request.approve', 'approval_request', (int) $request['id'], [
    'after' => ['summary' => $request['summary'], 'action_key' => $request['action_key'],
                'requested_by' => (int) $request['requested_by_member_id'], 'note' => $note],
]);

$outcome = replay_approved_request($request);
finish_approval_execution($pdo, (int) $request['id'], $outcome['ok'], $outcome['error']);
log_activity($pdo, 'approval_request.execute', 'approval_request', (int) $request['id'], [
    'after' => ['outcome' => $outcome['ok'] ? 'executed' : 'execution_failed', 'error' => $outcome['error'],
                'agent_run_id' => $request['agent_run_id'] !== null ? (int) $request['agent_run_id'] : null],
]);

settle_paused_run($pdo, $request);
$followUp = approvals_follow_up($request, 'approved',
    $outcome['ok'] ? 'It has been carried out' . ($outcome['did'] ? ': ' . $outcome['did'] . '.' : '.')
                   : 'It was approved but could NOT be carried out: ' . $outcome['error']);
if (!$outcome['ok']) {
    approvals_fail('Approved, but it could not be carried out: ' . $outcome['error'], 502);
}
approvals_decided($request, 'approved', $note, 'Approved and done: ' . ($outcome['did'] ?? $request['summary']),
    ['approval_request_id' => (int) $request['id'], 'follow_up_run_id' => $followUp]);
