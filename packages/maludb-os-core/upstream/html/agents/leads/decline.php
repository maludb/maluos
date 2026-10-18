<?php
declare(strict_types=1);

/** Action `agent_lead_decline` — log `agent_lead.decline`. Gate: super. A declined proposal is not filed again until a person asks (Propose leads). */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/assistants/assistants.php';

require_super_admin();
agent_refuse_agent_caller();
require_post();
verify_csrf();
$pdo = db();
$p = find_lead_proposal($pdo, (int) request_integer('proposal'));
if ($p === null || $p['status'] !== 'proposed') {
    emit_action_status(false, ['errors' => ['That proposal is not open.']]);
    respond_invalid(['That proposal is not open.']);
}
$note = mb_substr(trim(request_string('note')), 0, 500) ?: null;
check_approval($pdo, 'agent_lead_decline', 'agent_lead.decline', 'Decline ' . $p['name'], ['proposal' => (int) $p['id']], 'department', (int) $p['department_id']);
$pdo->prepare("UPDATE agent_lead_proposals SET status = 'declined', decided_by = :by, decided_at = now(), decision_note = :n WHERE id = :id")
    ->execute(['by' => (int) current_member_id(), 'n' => $note, 'id' => (int) $p['id']]);
log_activity($pdo, 'agent_lead.decline', 'department', (int) $p['department_id'], ['after' => ['proposal_id' => (int) $p['id'], 'note' => $note]]);
emit_action_status(true, ['did' => 'Declined ' . $p['name'], 'refresh' => 'agentChanged']);
