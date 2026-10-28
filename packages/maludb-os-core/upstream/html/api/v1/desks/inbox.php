<?php
declare(strict_types=1);

/**
 * The person's estate inbox (db/190; Bearer desk token). GET /api/v1/desks/inbox?wait=25[&all=1&since=ID] — unread
 * items (long-poll up to 25 s); POST …/inbox/ID/reply {"text", "envelope"}, …/ID/decide {"decision", "note",
 * "envelope"} (the desk's signed envelope), …/ID/read.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$ctx = desk_authenticate();
$pdo = db();
$id = api_path_id();
$sub = (string) ($_GET['sub'] ?? '');
if ($method === 'POST' && $id !== null && in_array($sub, ['reply', 'decide', 'read'], true)) {
    $body = json_decode((string) file_get_contents('php://input'), true);
    $body = is_array($body) ? $body : [];
    if ($sub === 'read') {
        api_json(['ok' => true, 'surface' => DESK_SURFACE, 'read' => inbox_mark_read($pdo, $ctx['member'], [$id])]);
    }
    $pdo->beginTransaction();
    $ans = inbox_answer($pdo, $ctx['member'], $id, $sub, $body, $ctx);
    $pdo->commit();
    api_json(['surface' => DESK_SURFACE] + $ans);
}
if ($method !== 'GET' || $id !== null) { api_error('method_not_allowed', 'GET the inbox, or POST …/ID/reply, …/ID/decide, …/ID/read.', 405); }
api_json(desk_inbox_answer($pdo, $ctx['member'], isset($_GET['wait']) && is_numeric($_GET['wait']) ? (float) $_GET['wait'] : 0.0, !empty($_GET['all']), isset($_GET['since']) && is_numeric($_GET['since']) ? (int) $_GET['since'] : 0));
