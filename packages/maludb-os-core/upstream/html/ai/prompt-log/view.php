<?php
declare(strict_types=1);

/**
 * Screen `prompt-log-view` — one call's full prompt and response. The ledger row through
 * mcp_prompt_ledger (else 404); the payload through mcp_prompt_payloads, which is narrower. A
 * payload past retention, or one this caller may not read, is SAID — never an error.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';

require_insider();

$pdo = db();
$id = request_integer('id');
if ($id === null || ($call = find_ledger_call($pdo, $id)) === null) {
    http_response_code(404);
    exit('Call not found.');
}
$payload = find_ledger_payload($pdo, $id);
$expired = ($call['payload_archived_at'] ?? null) !== null || ($payload !== null && $payload['archived_at'] !== null);
if (($_SERVER['HTTP_X_SCREEN_VIEW'] ?? '') === '1') {
    // One screen view, carrying WHICH call was opened (the rule html/api/v1/graph.php follows): who read which prompt
    // is worth knowing. The ledger id only — prompt text never reaches the activity trail.
    log_activity($pdo, 'screen.view', 'prompt_ledger', $id, ['screen' => 'prompt-log-view']);
}
$st = $pdo->prepare('SELECT id, action, entity_type, entity_id, occurred_at FROM activity_log WHERE request_id = :r AND action <> \'screen.view\' ORDER BY id LIMIT 20');
$st->execute(['r' => (string) $call['request_id']]);
respond_screen([
    'call' => present_ledger_call($call),
    'payload_state' => $payload === null ? 'none' : ($expired || ($payload['context'] === null && $payload['response'] === null) ? 'expired' : 'shown'),
    'context' => $payload !== null && !$expired ? present_payload_side($payload['context']) : null,
    'response' => $payload !== null && !$expired ? present_payload_side($payload['response']) : null,
    'actions' => array_map(static fn (array $a): array => ['id' => (int) $a['id'], 'action' => (string) $a['action'], 'entity_type' => $a['entity_type'],
        'entity_id' => $a['entity_id'] !== null ? (int) $a['entity_id'] : null, 'occurred_at' => json_ts($a['occurred_at'])], $st->fetchAll()),
    'verdicts' => present_verdicts(find_my_verdict($pdo, null, $id), find_verdicts($pdo, null, $id)),
    'can' => ['promote' => !is_agent_member() && (has_module_grant('evals') || aiops_can_see_agent($pdo, $call['agent_member_id'] !== null ? (int) $call['agent_member_id'] : null)),
              // The command bar is the most-used AI in the product; its answers deserve a label too.
              'verdict' => !is_agent_member()],
]);
