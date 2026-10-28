<?php
declare(strict_types=1);

/**
 * Action `agent_lead_confirm` — log `agent_lead.confirm` (and the hire's own entries). Gate: super; never
 * an agent. One click hires the proposed lead (db/157): an orchestrator in its department with the lead's
 * tools, the department's specialists on its roster, placed under the assistant whose person runs it.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/assistants/assistants.php';

require_super_admin();
agent_refuse_agent_caller();
require_post();
verify_csrf();
$pdo = db();
$p = find_lead_proposal($pdo, (int) request_integer('proposal'));
if ($p === null) {
    emit_action_status(false, ['errors' => ['That proposal does not exist.']]);
    respond_invalid(['That proposal does not exist.']);
}
check_approval($pdo, 'agent_lead_confirm', 'agent_lead.confirm', 'Hire ' . $p['name'], ['proposal' => (int) $p['id']], 'department', (int) $p['department_id']);
try {
    $memberId = confirm_lead_proposal($pdo, $p, (int) current_member_id());
} catch (RuntimeException | PDOException $e) {
    $why = $e instanceof RuntimeException ? $e->getMessage() : agent_trigger_message($e, 'The lead could not be hired.');
    emit_action_status(false, ['errors' => [$why]]);
    respond_invalid([$why]);
}
log_activity($pdo, 'agent_lead.confirm', 'department', (int) $p['department_id'], ['after' => ['proposal_id' => (int) $p['id'], 'member_id' => $memberId]]);
emit_action_status(true, ['did' => 'Hired ' . $p['name'] . ($p['parent_member_id'] !== null ? ' under your assistant' : ''), 'record_id' => $memberId, 'refresh' => 'agentChanged']);
header('HX-Push-Url: /agents/' . $memberId);
