<?php
declare(strict_types=1);

/**
 * Action `agent_add_subagent` — log `agent_subagent.create`. Gate: mod:hr, agent's manager
 * (OR). $agent must be an orchestrator and $subagent a subagent — refused by the db/072
 * agent_subagents_one_level trigger otherwise ("delegation is one level deep"), and refused by
 * the live-membership unique index if the pair is already on the roster. Both are caught below
 * and surfaced verbatim as a field error.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
$subagentId = request_integer('subagent');
$note = trim(request_string('note')) ?: null;
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}
agent_require_hr_or_manager($pdo, $agent);
agent_refuse_agent_caller();

if ($subagentId === null || ($subagent = find_agent($pdo, $subagentId)) === null) {
    render_agent_page($pdo, $id, 'roster', ['Choose a subagent to add.']);
}

check_approval($pdo, 'agent_add_subagent', 'agent_subagent.create',
    'Add ' . $subagent['display_name'] . " to " . $agent['display_name'] . "'s roster",
    ['agent' => $id, 'subagent' => $subagentId, 'note' => $note], 'member', $id);

try {
    $roster = add_agent_subagent($pdo, $id, $subagentId, $note, (int) current_member_id());
} catch (PDOException $ex) {
    error_log('agent add subagent failed: ' . $ex->getMessage());
    if ($ex->getCode() === '23505') {
        render_agent_page($pdo, $id, 'roster', [$subagent['display_name'] . ' is already on this roster.']);
    }
    render_agent_page($pdo, $id, 'roster', [agent_trigger_message($ex, 'That subagent could not be added.')]);
}
if ($roster === []) {
    render_agent_page($pdo, $id, 'roster', ['That subagent could not be added.']);
}

log_activity($pdo, 'agent_subagent.create', 'member', $id, [
    'after' => ['subagent_member_id' => $subagentId, 'subagent_name' => $subagent['display_name'], 'note' => $note],
]);
emit_action_status(true, [
    'did' => 'Added ' . $subagent['display_name'] . " to " . $agent['display_name'] . "'s roster",
    'refresh' => 'agentChanged',
]);
hx_trigger('agentChanged');
render_agent_page($pdo, $id, 'roster');
