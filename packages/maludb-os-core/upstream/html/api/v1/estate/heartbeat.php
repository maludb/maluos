<?php
declare(strict_types=1);

/**
 * POST /api/v1/estate/heartbeat — presence, facts and (every report_s) the report from a node (Bearer node token;
 * db/188). The report is evaluated against the fixed health rules and the estate's alerts follow it. Not logged
 * to activity. 410 once the node is retired; 400 invalid for a report over 32 KB.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
    api_error('method_not_allowed', 'Only POST is supported.', 405);
}
$ctx = node_authenticate();
$raw = (string) file_get_contents('php://input');
$body = json_decode($raw, true);
$body = is_array($body) ? $body : [];
$presence = (string) ($body['presence'] ?? 'online');
if (!in_array($presence, ['online', 'offline'], true)) {
    api_error('invalid', 'presence is online or offline.', 400);
}
if (isset($body['report']) && !is_array($body['report'])) {
    api_error('invalid', 'report is an object.', 400);
}
if (isset($body['report']) && strlen(json_encode($body['report'], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) ?: '') > NODE_REPORT_MAX_BYTES) {
    api_error('invalid', 'The report is over 32 KB.', 400);
}
$pdo = db();
$pdo->beginTransaction();
node_heartbeat($pdo, $ctx['node'], $presence, $body);
$row = node_row($pdo, (int) $ctx['node']['id']);
$changed = overlay_changed($pdo, $row);      // db/189: the overlay changed since this node last heard
$pdo->commit();
api_json(node_answer($pdo, $row) + ['overlay_changed' => $changed]);
