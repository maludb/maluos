<?php
declare(strict_types=1);

/**
 * POST /api/v1/estate/leave — the node retires itself (Bearer node token; db/188): status retired, offline, the
 * token revoked, its alerts cleared; logged as the operator who enrolled it, source node.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
    api_error('method_not_allowed', 'Only POST is supported.', 405);
}
$ctx = node_authenticate();
$pdo = db();
$id = (int) $ctx['node']['id'];
$pdo->beginTransaction();
node_retire($pdo, $id);
log_activity($pdo, 'node.leave', 'location', $id, ['source' => 'node',
    'before' => ['status' => 'active', 'name' => $ctx['node']['name']], 'after' => ['status' => 'retired']]);
$pdo->commit();
api_json(['ok' => true, 'surface' => DESK_SURFACE, 'node' => ['id' => $id, 'name' => (string) $ctx['node']['name'], 'status' => 'retired']]);
