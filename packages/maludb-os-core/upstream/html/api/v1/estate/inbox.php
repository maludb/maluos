<?php
declare(strict_types=1);

/**
 * The node's inbox (db/190; node token). GET /api/v1/estate/inbox?wait=25 — the tasks and actions queued for this
 * node, leased 120 s (long-poll up to 25 s). POST …/inbox/ID/result — the outcome of one: {"result": <task record
 * with state completed|failed|refused|pending_approval, output, provenance, usage, ask>} or {"refused": "reason"},
 * for an action {"result": {"ok": true|false, "output": …, "error": …}}.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$ctx = node_authenticate();
$pdo = db();
$itemId = isset($_GET['id']) && preg_match('/^[ta]_[0-9a-f]{12,32}$/', (string) $_GET['id']) ? (string) $_GET['id'] : null;
if ($method === 'POST' && $itemId !== null && ($_GET['sub'] ?? '') === 'result') {
    $body = json_decode((string) file_get_contents('php://input'), true);
    $pdo->beginTransaction();
    $ans = inbox_result($pdo, $ctx['node'], $itemId, is_array($body) ? $body : []);
    $pdo->commit();
    api_json($ans);
}
if ($method !== 'GET' || $itemId !== null) {
    api_error('method_not_allowed', 'GET the inbox, or POST …/ID/result.', 405);
}
api_json(node_inbox_answer($pdo, $ctx['node'], isset($_GET['wait']) && is_numeric($_GET['wait']) ? (float) $_GET['wait'] : 0.0));
