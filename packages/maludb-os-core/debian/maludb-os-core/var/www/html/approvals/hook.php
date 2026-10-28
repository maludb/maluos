<?php
declare(strict_types=1);

/**
 * The approval hook (A7 (d)) — the kernel's actions server asks this before it posts an action
 * with an approval category to an APPLICATION from us, as the caller (action token + relay). The
 * kernel's own handlers ask check_approval() themselves; an application's handler cannot reach the
 * policies, so the one write door asks on its behalf. If a policy matches, the request is recorded
 * with the application's handler URL and body — an approval replays it there, exactly as for a
 * kernel handler — and this answers 202 pending_approval; otherwise {proceed: true}.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/approvals/queries.php';

require_login();
require_post();
verify_csrf();
if (empty($GLOBALS['__action_authed'])) {
    json_error('forbidden', 'The approval hook is the actions server\'s to call.', 403);
}

$pdo = db();
$actionKey = trim(request_string('action_key'));
$logEvent = trim(request_string('log_event'));
$summary = trim(request_string('summary'));
$handlerUrl = trim(request_string('handler_url'));
$parameters = json_decode(request_string('parameters') ?: '{}', true);
$body = json_decode(request_string('body') ?: '{}', true);
$entityType = request_string('entity_type') ?: null;
$entityId = request_integer('entity_id');
$amount = request_string('amount') ?: null;
$currency = request_string('currency') ?: null;
if ($actionKey === '' || $logEvent === '' || !is_array($parameters) || !is_array($body)
    || !preg_match('#^https?://[^\s]+\.php$#', $handlerUrl)) {
    emit_action_status(false, ['errors' => ['action_key, log_event, an absolute handler_url ending in .php, parameters and body (JSON) are required.']]);
    respond_invalid(['action_key, log_event, an absolute handler_url ending in .php, parameters and body (JSON) are required.']);
}
$policy = approval_required($pdo, $logEvent, $amount, $currency);
if ($policy === null) {
    emit_action_status(true, ['did' => 'No approval policy applies to ' . $logEvent]);
    respond_saved(['proceed' => true]);
}
$requestId = create_approval_request($pdo, $policy, $actionKey, $summary !== '' ? $summary : $actionKey, $parameters,
    $entityType, $entityId, $amount, $currency, $handlerUrl, $body);
log_activity($pdo, 'approval_request.create', 'approval_request', $requestId, [
    'after' => ['action_key' => $actionKey, 'summary' => $summary, 'policy' => $policy['name'], 'handler_url' => $handlerUrl],
]);
emit_action_status(false, ['status' => 'pending_approval', 'did' => ($summary !== '' ? $summary : $actionKey) . ' waits for approval', 'approval_request_id' => $requestId]);
http_response_code(202);
header('Content-Type: application/json');
echo json_encode(['status' => 'pending_approval', 'did' => ($summary !== '' ? $summary : $actionKey) . ' waits for approval', 'approval_request_id' => $requestId]);
