<?php
declare(strict_types=1);

/**
 * Screen `approval-view` — /approvals/{id}: one request, and what the caller may do about it
 * (docs/build-specs/approvals.md). Visibility is mcp_approval_requests': the requester, the
 * approver, whoever decided it, a holder of the approvals grant, or someone who may see the
 * requesting agent. Invisible and missing are the same 404.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/approvals/queries.php';
require_once dirname(__DIR__, 2) . '/app/features/approvals/present.php';

require_login();

$pdo = db();
$id = request_integer('id');
$visible = null;
if ($id !== null) {
    $st = $pdo->prepare('SELECT 1 FROM mcp_approval_requests WHERE approval_request_id = :id');
    $st->execute(['id' => $id]);
    $visible = $st->fetchColumn();
}
if ($id === null || $visible === false || $visible === null || ($request = find_approval_request($pdo, $id)) === null) {
    http_response_code(404);
    exit('Approval request not found.');
}

log_screen_view($pdo, 'approval-view');

$me = (int) current_member_id();
$pending = $request['status'] === 'pending';
$human = !is_agent_member();
$mayCancel = (int) $request['requested_by_member_id'] === $me
    || ($request['requested_by_kind'] === 'agent' && nearest_human_manager($pdo, (int) $request['requested_by_member_id']) === $me);

respond_screen([
    'request' => present_approval_request($request),
    'can' => [
        'decide' => $pending && $human && (int) $request['approver_member_id'] === $me,
        'cancel' => $pending && $human && $mayCancel,
    ],
]);
