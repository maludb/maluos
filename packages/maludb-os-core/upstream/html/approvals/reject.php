<?php
declare(strict_types=1);

/** Action `approval_reject` — refuse a paused action; it never runs. Gate: the request's approver. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/approvals/decide.php';

require_post();
verify_csrf();
[$pdo, $request] = approvals_open_request();

if ((int) $request['approver_member_id'] !== current_member_id()) {
    deny('Only ' . $request['approver_name'] . ' can decide this request.');
}
$reason = trim(request_string('reason'));
if ($reason === '') {
    approvals_fail('Say why — the requester reads the reason.');
}
if ($request['status'] !== 'pending') {
    approvals_fail('That request is ' . $request['status'] . ' — it can no longer be rejected.', 409);
}
if (!decide_approval_request($pdo, (int) $request['id'], 'rejected', (int) current_member_id(), $reason)) {
    approvals_fail('That request was decided by someone else a moment ago.', 409);
}
log_activity($pdo, 'approval_request.reject', 'approval_request', (int) $request['id'], [
    'after' => ['summary' => $request['summary'], 'action_key' => $request['action_key'],
                'requested_by' => (int) $request['requested_by_member_id'], 'reason' => $reason],
]);
settle_paused_run($pdo, $request);
$followUp = approvals_follow_up($request, 'rejected', 'Reason: ' . $reason);
approvals_decided($request, 'rejected', $reason, 'Rejected: ' . $request['summary'],
    ['approval_request_id' => (int) $request['id'], 'follow_up_run_id' => $followUp]);
