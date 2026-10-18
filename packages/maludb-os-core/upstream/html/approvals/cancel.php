<?php
declare(strict_types=1);

/**
 * Action `approval_cancel` — withdraw a request before it is decided. Gate: the requester; for an
 * agent requester, the nearest human up its management chain (its direct manager may be an
 * orchestrator agent, who may not) — the agent's run is over and cannot cancel for itself.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/approvals/decide.php';

require_post();
verify_csrf();
[$pdo, $request] = approvals_open_request();

$me = current_member_id();
$mayCancel = (int) $request['requested_by_member_id'] === $me
    || ($request['requested_by_kind'] === 'agent'
        && nearest_human_manager($pdo, (int) $request['requested_by_member_id']) === $me);
if (!$mayCancel) {
    deny('Only whoever asked can withdraw a request.');
}
if ($request['status'] !== 'pending') {
    approvals_fail('That request is ' . $request['status'] . ' — it can no longer be withdrawn.', 409);
}
if (!decide_approval_request($pdo, (int) $request['id'], 'cancelled', (int) $me, null)) {
    approvals_fail('That request was decided a moment ago.', 409);
}
log_activity($pdo, 'approval_request.cancel', 'approval_request', (int) $request['id'], [
    'after' => ['summary' => $request['summary'], 'action_key' => $request['action_key']],
]);
settle_paused_run($pdo, $request);
notify_approval_withdrawn($pdo, $request);
approvals_done('Withdrawn: ' . $request['summary'], ['approval_request_id' => (int) $request['id']]);
