<?php
declare(strict_types=1);

/**
 * GET /api/v1/desks/agents — the estate's agent directory as this desk sees it (Bearer desk token; Phase 12 slice 8's
 * shape, fed by db/190): id, name, description, icon, capabilities, presence, state, node, tasks (the task
 * interface's URL) and activity. POST …/agents/ID/tasks: JSON-RPC (agent/card, tasks/send with the desk's envelope,
 * tasks/get, tasks/list). GET …/agents/ID/activity: the agent's recent tasks as the caller may see them.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$ctx = desk_authenticate();
$pdo = db();
$id = api_path_id();
$sub = (string) ($_GET['sub'] ?? '');
if ($id !== null) {
    $agent = agent_find($pdo, $id) ?? api_error('not_found', 'No such agent.', 404);
    if ($method === 'POST' && $sub === 'tasks') { agent_rpc_answer($pdo, $agent, $ctx); }
    if ($method === 'GET' && $sub === 'activity') {
        $ans = agent_rpc($pdo, $agent, ['method' => 'tasks/list', 'params' => ['limit' => 50]], $ctx);
        $rows = array_map(static fn (array $t) => ['ts' => $t['ts'], 'kind' => 'task', 'actor' => $t['originator'], 'summary' => "task {$t['id']} {$t['state']}: " . mb_substr($t['input']['text'], 0, 60)], $ans['result']['tasks'] ?? []);
        api_json(['ok' => true, 'surface' => DESK_SURFACE, 'activity' => $rows]);
    }
    if ($method === 'GET') { api_json(['ok' => true, 'surface' => DESK_SURFACE, 'agent' => present_agent($agent)]); }
    api_error('method_not_allowed', 'GET, GET …/activity or POST …/tasks.', 405);
}
api_require_get();
$cap = isset($_GET['capability']) ? (string) $_GET['capability'] : null;
$out = [];
foreach (estate_agents_answer($pdo, $cap)['agents'] as $a) {
    $out[] = ['id' => (string) $a['id'], 'name' => $a['display_name'] ?: $a['name'], 'agent' => $a['name'], 'description' => $a['description'], 'icon' => 'maluos-logo',
              'capabilities' => $a['capabilities'], 'owner' => $a['owner'], 'accept_from' => $a['accept_from'], 'max_classification' => $a['max_classification'],
              'node' => $a['node']['name'], 'node_ref' => $a['node']['ref'], 'node_kind' => $a['node']['kind'], 'presence' => $a['presence'], 'state' => $a['state'],
              'principal' => $a['principal'], 'hired' => $a['hired'],
              'tasks' => $a['tasks'] !== null ? app_url('/api/v1/desks/agents/' . $a['id'] . '/tasks') : null,
              'activity' => app_url('/api/v1/desks/agents/' . $a['id'] . '/activity'), 'page' => app_url('/settings/desks')];
}
api_json(['ok' => true, 'surface' => DESK_SURFACE, 'agents' => $out, 'fetched_at' => gmdate('Y-m-d\TH:i:s\Z')]);
