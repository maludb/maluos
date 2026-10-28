<?php
declare(strict_types=1);

/**
 * Action `agent_remove_subagent` — log `agent_subagent.remove`. Gate: mod:hr, agent's manager
 * (OR). Sets removed_at; never deletes, so the roster's history stays auditable (db/072).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
$subagentId = request_integer('subagent');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}
agent_require_hr_or_manager($pdo, $agent);
agent_refuse_agent_caller();

$subagent = $subagentId !== null ? find_agent($pdo, $subagentId) : null;
if ($subagent === null) {
    render_agent_page($pdo, $id, 'roster', ['That subagent does not exist.']);
}

check_approval($pdo, 'agent_remove_subagent', 'agent_subagent.remove',
    'Remove ' . $subagent['display_name'] . ' from ' . $agent['display_name'] . "'s roster",
    ['agent' => $id, 'subagent' => $subagentId], 'member', $id);

try {
    $removed = remove_agent_subagent($pdo, $id, $subagentId);
} catch (PDOException $ex) {
    error_log('agent remove subagent failed: ' . $ex->getMessage());
    render_agent_page($pdo, $id, 'roster', [agent_trigger_message($ex, 'That subagent could not be removed.')]);
}
if (!$removed) {
    render_agent_page($pdo, $id, 'roster', ['That subagent is not on this roster.']);
}

log_activity($pdo, 'agent_subagent.remove', 'member', $id, [
    'before' => ['subagent_member_id' => $subagentId, 'subagent_name' => $subagent['display_name']],
]);
emit_action_status(true, [
    'did' => 'Removed ' . $subagent['display_name'] . ' from ' . $agent['display_name'] . "'s roster",
    'refresh' => 'agentChanged',
]);
hx_trigger('agentChanged');
render_agent_page($pdo, $id, 'roster');
