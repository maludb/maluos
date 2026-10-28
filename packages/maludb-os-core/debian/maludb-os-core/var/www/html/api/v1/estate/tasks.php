<?php
declare(strict_types=1);

/** GET /api/v1/estate/tasks/ID — a task's record with its provenance (db/190; the originator's or sender's token, the agent's node, an operator). ?wait=N waits for it to finish. */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

$ctx = estate_authenticate_any();
$pdo = db();
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    // tasks/send without naming an agent: the envelope's target is {"agent", "node"} or {"capability"}; the kernel resolves it against the directory
    $req = json_decode((string) file_get_contents('php://input'), true);
    if (!is_array($req) || ($req['method'] ?? null) !== 'tasks/send') { api_json(['jsonrpc' => '2.0', 'id' => is_array($req) ? ($req['id'] ?? null) : null, 'error' => ['code' => -32601, 'message' => 'POST /api/v1/estate/tasks takes tasks/send only']]); }
    $env = is_array($req['params']['envelope'] ?? null) ? $req['params']['envelope'] : [];
    $tgt = is_array($env['target'] ?? null) ? $env['target'] : [];
    $agent = null;
    if (is_string($tgt['agent'] ?? null)) {
        $p = node_ref_parse($tgt['node'] ?? null);
        $st = $pdo->prepare("SELECT id FROM estate_agents WHERE name = :n AND status = 'active' AND " . ($p !== null && $p[0] !== 'coordinator' ? 'location_id = :loc' : ($p !== null ? 'location_id IS NULL' : 'true')) . ' ORDER BY last_seen_at DESC LIMIT 1');
        $st->execute(['n' => $tgt['agent']] + ($p !== null && $p[0] !== 'coordinator' ? ['loc' => $p[1]] : []));
        $aid = $st->fetchColumn();
        $agent = $aid !== false ? agent_find($pdo, (int) $aid) : null;
    } elseif (is_string($tgt['capability'] ?? null)) {
        $agent = agent_resolve_capability($pdo, $tgt['capability'], is_array($env['originator'] ?? null) ? $env['originator'] + ['member_id' => isset($ctx['desk']) ? (int) $ctx['member']['id'] : ($env['originator']['member_id'] ?? null)] : []);
    }
    if ($agent === null) { api_json(['jsonrpc' => '2.0', 'id' => $req['id'] ?? null, 'error' => ['code' => -32004, 'message' => 'No agent in the directory answers that target.', 'data' => ['reason' => 'no_agent']]]); }
    $ans = agent_rpc($pdo, $agent, $req, $ctx);
    api_json(['jsonrpc' => '2.0', 'id' => $req['id'] ?? null] + $ans);
}
api_require_get();
$id = isset($_GET['id']) && preg_match('/^t_[0-9a-f]{12,32}$/', (string) $_GET['id']) ? (string) $_GET['id'] : api_error('not_found', 'No such task.', 404);
$t = task_row($pdo, $id);
if ($t === [] || !task_visible($t, $ctx)) { api_error('not_found', 'No such task.', 404); }
if (isset($_GET['wait']) && is_numeric($_GET['wait'])) { $t = task_wait($pdo, $id, (float) $_GET['wait']); }
api_json(['ok' => true, 'surface' => DESK_SURFACE, 'task' => present_task($t)]);
