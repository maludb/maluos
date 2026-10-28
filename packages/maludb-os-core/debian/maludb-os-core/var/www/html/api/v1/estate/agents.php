<?php
declare(strict_types=1);

/**
 * The estate's agent directory (db/190). GET /api/v1/estate/agents[?capability=X&node=N] (node or desk token): the
 * active agents; GET …/agents/ID: one. POST …/agents (node token): register this node's agents (the manifest
 * list, replacing what it registered before). POST …/agents/ID/tasks (node or desk token): the agent's task
 * interface, JSON-RPC (agent/card, tasks/send with an envelope, tasks/get, tasks/list).
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$id = api_path_id();
$sub = (string) ($_GET['sub'] ?? '');
$pdo = db();
if ($method === 'POST' && $id !== null && $sub === 'tasks') {
    $ctx = estate_authenticate_any();
    $agent = agent_find($pdo, $id) ?? api_error('not_found', 'No such agent.', 404);
    agent_rpc_answer($pdo, $agent, $ctx);
}
if ($method === 'POST' && $id === null) {
    $ctx = node_authenticate();
    $body = json_decode((string) file_get_contents('php://input'), true);
    if (!is_array($body) || !is_array($body['agents'] ?? null)) {
        api_error('invalid', 'agents is a list of manifests.', 400);
    }
    $pdo->beginTransaction();
    $r = agents_register($pdo, $ctx['node'], $body['agents']);
    log_activity($pdo, 'estate.agents.register', 'location', (int) $ctx['node']['id'], ['source' => 'node', 'after' => $r + ['names' => array_values(array_filter(array_map(static fn ($a) => is_array($a) ? ($a['name'] ?? null) : null, $body['agents'])))]]);
    $pdo->commit();
    api_json(['ok' => true, 'surface' => DESK_SURFACE] + $r + ['agents' => estate_agents_answer($pdo, null, (int) $ctx['node']['id'])['agents']]);
}
if ($method !== 'GET') {
    api_error('method_not_allowed', 'GET, or POST to register or to …/ID/tasks.', 405);
}
$ctx = estate_authenticate_any();
if ($id !== null) {
    $agent = agent_find($pdo, $id);
    if ($agent === null) { api_error('not_found', 'No such agent.', 404); }
    api_json(['ok' => true, 'surface' => DESK_SURFACE, 'agent' => present_agent($agent)]);
}
$node = isset($_GET['node']) && is_numeric($_GET['node']) ? (int) $_GET['node'] : null;
api_json(estate_agents_answer($pdo, isset($_GET['capability']) ? (string) $_GET['capability'] : null, $node, !empty($_GET['all']) && (isset($ctx['node']) || estate_operator($ctx['member']))));
