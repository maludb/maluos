<?php
declare(strict_types=1);

/**
 * Action `agent_set_kind` — log `agent.set_kind`. Gate: mod:hr (no manager OR — unlike the
 * config-version write, changing what KIND of agent this is stays HR-only). Refused by the
 * db/072 agent_profiles_kind_change trigger while a live roster still depends on the current
 * kind, and by the agent_office_manager_is_orchestrator CHECK if this agent is its location's
 * office manager (which requires staying an orchestrator) — both caught below and surfaced
 * verbatim, never a generic "could not save".
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_module_grant('hr');
agent_refuse_agent_caller();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
$kind = request_string('agent_kind');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}
if (!in_array($kind, AGENT_KINDS, true)) {
    render_agent_page($pdo, $id, 'job', ['Kind must be orchestrator or subagent.']);
}
if ($kind === $agent['agent_kind']) {
    render_agent_page($pdo, $id, 'job', [$agent['display_name'] . ' is already ' . $kind . '.']);
}

check_approval($pdo, 'agent_set_kind', 'agent.set_kind',
    'Set kind for ' . $agent['display_name'] . ' to ' . $kind,
    ['agent' => $id, 'agent_kind' => $kind], 'member', $id);

try {
    $after = set_agent_kind($pdo, $id, $kind);
} catch (PDOException $ex) {
    error_log('agent set kind failed: ' . $ex->getMessage());
    render_agent_page($pdo, $id, 'job', [agent_trigger_message($ex, 'The kind could not be changed.')]);
}
if ($after === []) {
    render_agent_page($pdo, $id, 'job', ['The kind could not be changed.']);
}

log_activity($pdo, 'agent.set_kind', 'member', $id, [
    'before' => ['agent_kind' => $agent['agent_kind']],
    'after' => ['agent_kind' => $after['agent_kind']],
]);
emit_action_status(true, [
    'did' => 'Set kind for ' . $after['display_name'] . ' to ' . $kind,
    'refresh' => 'agentChanged',
]);
hx_trigger('agentChanged');
render_agent_page($pdo, $id, 'job');
