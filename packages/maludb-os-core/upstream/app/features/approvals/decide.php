<?php
declare(strict_types=1);

/**
 * Shared opening of the three decision handlers: load the feature files, refuse an agent caller
 * (a decision is "never delegable to agents" — manifest), find the request, expire it if its time
 * has passed. Returns [pdo, request].
 */
require_once __DIR__ . '/queries.php';
require_once __DIR__ . '/replay.php';
require_once __DIR__ . '/present.php';
require_once __DIR__ . '/notify.php';
require_once dirname(__DIR__) . '/agents/runs.php';

function approvals_open_request(): array
{
    require_login();
    if (is_agent_member()) {
        deny('An agent may ask for approval, never give, refuse or withdraw one.');
    }
    $pdo = db();
    $id = request_integer('approval_request');
    $request = $id !== null ? find_approval_request($pdo, $id) : null;
    if ($request === null) {
        http_response_code(404);
        exit('Approval request not found.');
    }
    if (expire_approval_if_due($pdo, (int) $request['id'])) {
        log_activity($pdo, 'approval_request.expire', 'approval_request', (int) $request['id'], [
            'after' => ['summary' => $request['summary']],
        ]);
        $request['status'] = 'expired';
        settle_paused_run($pdo, $request);
    }
    return [$pdo, $request];
}

function approvals_fail(string $message, int $status = 422): never
{
    http_response_code($status);
    emit_action_status(false, ['errors' => [$message]]);
    echo '<div class="alert alert-danger m-4" role="alert">' . e($message) . '</div>';
    exit;
}

function approvals_done(string $did, array $extra = []): never
{
    emit_action_status(true, ['did' => $did, 'refresh' => 'approvalChanged'] + $extra);
    echo '<div class="alert alert-success m-4" role="status">' . e($did) . '.</div>';
    exit;
}

/**
 * The end of every decision: tell whoever asked, then answer the approver. One call, so a new
 * decision handler cannot be written that forgets it.
 */
function approvals_decided(array $request, string $decision, ?string $note, string $did, array $extra = []): never
{
    notify_approval_decided(db(), $request, $decision, $note);
    approvals_done($did, $extra);
}

/** Tell the agent what was decided and let it carry on — only when the approver asks for it. */
function approvals_follow_up(array $request, string $decision, ?string $detail): ?int
{
    if (!request_bool('follow_up') || $request['requested_by_kind'] !== 'agent' || $request['agent_run_id'] === null) {
        return null;
    }
    $pdo = db();
    $run = find_agent_run($pdo, (int) $request['agent_run_id']);
    $text = 'A decision was made on something you asked approval for in run #' . (int) $request['agent_run_id'] . ".\n"
        . 'Request: ' . $request['summary'] . "\nDecision: " . $decision . ' by ' . (current_member()['display_name'] ?? 'your approver') . '.'
        . ($detail !== null && $detail !== '' ? "\n" . $detail : '')
        . "\n\nYour original instructions were:\n" . (string) ($run['instructions'] ?? '(not recorded)')
        . "\n\nDo not repeat the request. Continue with whatever is left of that work, or report that nothing is.";
    [$started] = start_agent_run((int) $request['requested_by_member_id'], $text, 'manual', null,
        (int) current_member_id(), (int) $request['agent_run_id']);
    return $started !== null ? (int) $started['run_id'] : null;
}
