<?php
declare(strict_types=1);

/**
 * RetellAI inbound-call webhook: when a call reaches one of our numbers, answer with the voice
 * agent's live system prompt (db/091, db/093).
 *
 * Not a screen and not a manifest action — no member is present. The caller is Retell, proved
 * by the X-Retell-Signature HMAC over (body . timestamp) with RETELL_API_KEY, and everything
 * it is told is decided by the number that was dialled.
 *
 * Retell waits ten seconds and retries twice on failure, so every path here answers at once and
 * logs what it did. `{"call_inbound": {}}` is the honest "no override" answer: it leaves the
 * call to whatever Retell already has configured, which is what an unknown number, an agent
 * that is not active, or an agent with no configuration version should get. The call is never
 * rejected from here — declining to override is ours to decide, hanging up on a customer is not.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/voice.php';

header('Content-Type: application/json');

/** Answer Retell and stop. Every exit goes through here so nothing ever hangs the call. */
$answer = static function (array $callInbound, int $status = 200): never {
    http_response_code($status);
    echo json_encode(['call_inbound' => (object) $callInbound], JSON_UNESCAPED_SLASHES);
    exit;
};

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
    http_response_code(405);
    header('Allow: POST');
    exit('{"error":"POST only"}');
}

$rawBody = (string) file_get_contents('php://input');
$failure = retell_signature_failure($rawBody, (string) ($_SERVER['HTTP_X_RETELL_SIGNATURE'] ?? ''), retell_api_key());
if ($failure !== null) {
    // Never echo the reason: an attacker learning "timestamp too old" versus "digest wrong" is
    // being told how to try again. It goes to the error log, where the operator can read it.
    error_log('retell inbound webhook refused: ' . $failure);
    http_response_code(401);
    exit('{"error":"unauthorized"}');
}

$payload = json_decode($rawBody, true);
$inbound = is_array($payload) ? ($payload['call_inbound'] ?? null) : null;
if (($payload['event'] ?? '') !== 'call_inbound' || !is_array($inbound)) {
    error_log('retell inbound webhook: unexpected payload event=' . (string) ($payload['event'] ?? '(none)'));
    $answer([]);
}

$toNumber = trim((string) ($inbound['to_number'] ?? ''));
$fromNumber = trim((string) ($inbound['from_number'] ?? ''));
$callId = trim((string) ($inbound['call_id'] ?? ''));

$pdo = db();
$agent = $toNumber === '' ? null : voice_agent_for_number($pdo, $toNumber);

if ($agent === null) {
    log_activity($pdo, 'voice_call.unrouted', null, null, [
        'source' => 'webhook',
        'after' => ['to_number' => $toNumber, 'from_number' => $fromNumber, 'call_id' => $callId],
    ]);
    $answer([]);
}

$memberId = (int) $agent['member_id'];
$response = $agent['status'] === 'active' ? retell_inbound_response($agent, business_name($pdo)) : [];

log_activity($pdo, 'voice_call.inbound', 'member', $memberId, [
    'source' => 'webhook',
    'actor_member_id' => $memberId,          // the agent answered; the caller is not a member
    'after' => [
        'call_id' => $callId,
        'to_number' => $toNumber,
        'from_number' => $fromNumber,
        'agent_status' => $agent['status'],
        'config_version_id' => $agent['config_version_id'] !== null ? (int) $agent['config_version_id'] : null,
        'prompt_supplied' => $response !== [],
    ],
]);

$answer($response);
