<?php
declare(strict_types=1);

/**
 * Action `escalation_resolve` — log `agent_escalation.resolve`. Gate: escalation recipient,
 * agent's manager (OR) — no mod:hr fallback (the manifest names exactly these two).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_login();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('escalation');
$note = request_string('note') ?: null;
$escalation = $id !== null ? find_escalation($pdo, $id) : null;
if ($escalation === null) {
    http_response_code(404);
    exit('Escalation not found.');
}

$agent = find_agent($pdo, (int) $escalation['agent_member_id']);
$me = (int) current_member_id();
$isRecipient = (int) ($escalation['to_member_id'] ?? 0) === $me;
$isManager = (int) ($agent['manager_member_id'] ?? 0) === $me;
if (!$isRecipient && !$isManager) {
    deny('Only the escalation\'s recipient, or this agent\'s manager, may resolve it.');
}

check_approval($pdo, 'escalation_resolve', 'agent_escalation.resolve',
    'Resolve escalation for ' . ($agent['display_name'] ?? 'agent'),
    ['escalation' => $id, 'note' => $note], 'agent_escalation', $id);

$after = resolve_escalation($pdo, $id, $note, $me);
if ($after === []) {
    render_escalations_page($pdo, ['That escalation is already resolved.']);
}

log_activity($pdo, 'agent_escalation.resolve', 'agent_escalation', $id, [
    'after' => ['resolved_by' => $me, 'note' => $note],
]);
emit_action_status(true, ['did' => 'Resolved escalation', 'refresh' => 'escalationChanged']);
hx_trigger('escalationChanged');
render_escalations_page($pdo);
