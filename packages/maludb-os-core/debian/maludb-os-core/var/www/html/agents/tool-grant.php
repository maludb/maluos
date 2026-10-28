<?php
declare(strict_types=1);

/**
 * Grant a tool to an agent (Tools tab). Not its own manifest action — agent_update_config is
 * the voice/API surface for a full tools[] replace; this is the interactive quick-grant used
 * from the Tools tab, editing the live agent_tool_grants directly. Gate: mod:hr, agent's
 * manager (OR), matching agent_update_config's gate since this changes the same config.
 * Log: agent_tool_grant.create (no matching hr_events type — activity_log only).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}
agent_require_hr_or_manager($pdo, $agent);
agent_refuse_agent_caller();

$endpointId = request_integer('application_endpoint_id');
$tool = request_string('tool_name');
$constraintsRaw = trim(request_string('constraints'));
if ($endpointId === null || $tool === '') {
    render_agent_page($pdo, $id, 'tools', ['A tool grant needs an MCP endpoint and a tool name.']);
}
$constraints = [];
if ($constraintsRaw !== '') {
    $decoded = json_decode($constraintsRaw, true);
    if (!is_array($decoded)) {
        render_agent_page($pdo, $id, 'tools', ['Constraints must be valid JSON, e.g. {"max_amount": 500}.']);
    }
    $constraints = $decoded;
}

// For a readable label only (approval description, activity log) — not a gate. Whether this
// endpoint actually qualifies (kind='mcp', agent_reachable, active) is enforced by the
// agent_tool_grants_endpoint_valid trigger below, and its own message is what a refusal shows.
$endpointOption = find_application_endpoint_option($pdo, $endpointId);
$endpointLabel = $endpointOption !== null
    ? $endpointOption['application_name'] . ' — ' . $endpointOption['endpoint_name']
    : 'endpoint #' . $endpointId;

// A name the server does not offer grants nothing (enforcement is server-side), so say so here.
// Only our own servers can be asked; for any other endpoint the grant is saved unchecked.
if (mb_strlen($tool) > 100) {
    render_agent_page($pdo, $id, 'tools', ['That tool name is too long to be one.']);
}
$offered = $endpointOption !== null ? mcp_endpoint_tool_names($endpointOption, (int) current_member_id()) : null;
if ($offered !== null && !in_array($tool, $offered, true)) {
    render_agent_page($pdo, $id, 'tools', [mcp_unknown_tool_message($tool, $endpointLabel, $offered)]);
}

check_approval($pdo, 'agent_tool_grant', 'agent_tool_grant.create',
    'Grant ' . $endpointLabel . ':' . $tool . ' to ' . $agent['display_name'],
    ['agent' => $id, 'application_endpoint_id' => $endpointId, 'tool_name' => $tool], 'member', $id);

try {
    $grant = grant_agent_tool($pdo, $id, $endpointId, $tool, $constraints, (int) current_member_id());
} catch (PDOException $ex) {
    render_agent_page($pdo, $id, 'tools', [agent_trigger_message($ex, 'That tool grant could not be saved.')]);
}
if ($grant === []) {
    render_agent_page($pdo, $id, 'tools', ['That tool grant could not be saved.']);
}

log_activity($pdo, 'agent_tool_grant.create', 'member', $id, [
    'after' => [
        'application_endpoint_id' => $endpointId,
        'endpoint_name' => $grant['endpoint_name'] ?? null,
        'application_name' => $grant['application_name'] ?? null,
        'tool_name' => $tool, 'constraints' => $constraints,
    ],
]);
emit_action_status(true, [
    'did' => 'Granted ' . ($grant['application_name'] ?? $endpointLabel) . ' — ' . ($grant['endpoint_name'] ?? '') . ':' . $tool,
    'refresh' => 'agentChanged',
]);
hx_trigger('agentChanged');
render_agent_page($pdo, $id, 'tools');
