<?php
declare(strict_types=1);

/** Revoke a tool grant (Tools tab). See tool-grant.php for why this has no manifest row.
 *  Gate: mod:hr, agent's manager (OR). Log: agent_tool_grant.revoke. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
$grantId = request_integer('grant');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}
agent_require_hr_or_manager($pdo, $agent);
agent_refuse_agent_caller();

$grant = $grantId !== null ? find_agent_tool_grant($pdo, $grantId) : null;
if ($grant === null || (int) $grant['agent_member_id'] !== $id) {
    render_agent_page($pdo, $id, 'tools', ['That tool grant does not belong to this agent.']);
}

$endpointOption = find_application_endpoint_option($pdo, (int) $grant['application_endpoint_id']);
$endpointLabel = $endpointOption !== null
    ? $endpointOption['application_name'] . ' — ' . $endpointOption['endpoint_name']
    : 'endpoint #' . $grant['application_endpoint_id'];

check_approval($pdo, 'agent_tool_revoke', 'agent_tool_grant.revoke',
    'Revoke ' . $endpointLabel . ':' . $grant['tool_name'] . ' from ' . $agent['display_name'],
    ['agent' => $id, 'grant' => $grantId], 'member', $id);

revoke_agent_tool($pdo, $grantId);
log_activity($pdo, 'agent_tool_grant.revoke', 'member', $id, [
    'before' => [
        'application_endpoint_id' => $grant['application_endpoint_id'],
        'endpoint_name' => $endpointOption['endpoint_name'] ?? null,
        'tool_name' => $grant['tool_name'],
    ],
]);
emit_action_status(true, ['did' => 'Revoked ' . $endpointLabel . ':' . $grant['tool_name'], 'refresh' => 'agentChanged']);
hx_trigger('agentChanged');
render_agent_page($pdo, $id, 'tools');
