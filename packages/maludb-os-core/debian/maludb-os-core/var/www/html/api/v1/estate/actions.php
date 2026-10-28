<?php
declare(strict_types=1);

/**
 * A system manager's action on a node (db/190). POST /api/v1/estate/nodes/ID/actions (desk token, an operator):
 * {"action": restart_agent|start_agent|stop_agent|apply_updates|reboot, "agent": NAME, "envelope": {…}, "wait": 30}
 * — queued to the node, which runs only what its own actions.allow permits. GET /api/v1/estate/actions/ID (the
 * requester, an operator, or the node): the action's state and result; GET /api/v1/estate/actions: the last 50.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$pdo = db();
if ($method === 'POST') {
    $ctx = desk_authenticate();
    if (!estate_operator($ctx['member'])) { api_error('forbidden', 'Node actions are an operator\'s.', 403); }
    $nodeId = isset($_GET['node']) && is_numeric($_GET['node']) ? (int) $_GET['node'] : api_error('not_found', 'No such node.', 404);
    $node = node_row($pdo, $nodeId);
    if ($node === [] || $node['status'] !== 'active') { api_error('not_found', 'No such node.', 404); }
    $body = json_decode((string) file_get_contents('php://input'), true);
    $body = is_array($body) ? $body : [];
    if (!is_array($body['envelope'] ?? null)) { api_error('envelope_required', 'A node action carries the desk\'s envelope.', 400); }
    $pdo->beginTransaction();
    $a = action_create($pdo, $node, (string) ($body['action'] ?? ''), is_string($body['agent'] ?? null) ? $body['agent'] : null, $body['envelope'], $ctx);
    $pdo->commit();
    if (isset($body['wait']) && is_numeric($body['wait']) && (float) $body['wait'] > 0) { $a = action_wait($pdo, $a['id'], (float) $body['wait']); }
    api_json(['ok' => true, 'surface' => DESK_SURFACE, 'action' => present_action($a)], 201);
}
if ($method !== 'GET') { api_error('method_not_allowed', 'GET, or POST to /api/v1/estate/nodes/ID/actions.', 405); }
$ctx = estate_authenticate_any();
$id = isset($_GET['id']) && preg_match('/^a_[0-9a-f]{12,32}$/', (string) $_GET['id']) ? (string) $_GET['id'] : null;
if ($id !== null) {
    $a = action_row($pdo, $id);
    $mine = $a !== [] && (isset($ctx['node']) ? (int) $a['location_id'] === (int) $ctx['node']['id'] : (estate_operator($ctx['member']) || (int) $a['requested_by_member_id'] === (int) $ctx['member']['id']));
    if (!$mine) { api_error('not_found', 'No such action.', 404); }
    if (isset($_GET['wait']) && is_numeric($_GET['wait'])) { $a = action_wait($pdo, $id, (float) $_GET['wait']); }
    api_json(['ok' => true, 'surface' => DESK_SURFACE, 'action' => present_action($a)]);
}
if (isset($ctx['node'])) {
    $st = $pdo->prepare('SELECT a.*, l.name AS node_name FROM estate_actions a JOIN locations l ON l.id = a.location_id WHERE a.location_id = :loc ORDER BY a.created_at DESC LIMIT 50');
    $st->execute(['loc' => (int) $ctx['node']['id']]);
} elseif (estate_operator($ctx['member'])) {
    $st = $pdo->query('SELECT a.*, l.name AS node_name FROM estate_actions a JOIN locations l ON l.id = a.location_id ORDER BY a.created_at DESC LIMIT 50');
} else {
    api_error('forbidden', 'Node actions are an operator\'s.', 403);
}
api_json(['ok' => true, 'surface' => DESK_SURFACE, 'actions' => array_map('present_action', $st->fetchAll())]);
