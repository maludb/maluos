<?php
declare(strict_types=1);
/**
 * Proof of the node actions for the watching agents (db/197; MaluOS Phase 14 slice 4d, maluos
 * docs/phase14-watching-agents.md), at the level of the kernel's own functions: the arguments' checks, an action
 * the kernel originates with the coordinator's envelope, what the node's inbox hands over, its result, and the
 * approval policy that pauses an agent's request. The handler html/estate/node-action.php over HTTP, the approval
 * and the node are proven by MaluOS's boot test, which has a runner, an agent and a node.
 *
 *   php bin/test_node_actions.php
 *
 * Makes one server node named SMOKE NA <run> and retires it at the end.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/estate/nodes.php';
require_once dirname(__DIR__) . '/app/features/approvals/queries.php';
$pdo = db();
$admin = $pdo->query("SELECT * FROM members WHERE business_role = 'super_admin' AND status = 'active' AND member_kind = 'human' ORDER BY id LIMIT 1")->fetch();
$_SESSION['member_id'] = (int) $admin['id'];
db_apply_context($pdo);
$fails = 0;
$ok = static function (bool $c, string $label) use (&$fails): void { if (!$c) { $fails++; } echo ($c ? '  ok   ' : '  FAIL ') . $label . "\n"; };
$run = date('md-His');

echo "== the arguments\n";
$ok(action_args('restart_unit', null, ['unit' => 'postgresql@18-main.service']) === [['unit' => 'postgresql@18-main.service'], null], 'restart_unit takes a service unit');
$bad = ['', 'apache2', 'apache2.timer', '../x.service', 'a b.service', 'x.service; reboot', str_repeat('a', 130) . '.service'];
$ok(array_filter($bad, static fn ($u) => !is_string(action_args('restart_unit', null, ['unit' => $u]))) === [], 'and nothing else: no unit, another unit type, a path, a space, a command, an overlong name');
$ok(action_args('postgres_cancel', null, ['pid' => '4242']) === [['pid' => 4242], null] && action_args('postgres_terminate', null, ['pid' => 4242]) === [['pid' => 4242], null], 'postgres_cancel and postgres_terminate take a pid');
$ok(array_filter([null, '', '0', '1', '-5', '12; select 1', '4242 or 1=1', '99999999', 12.5], static fn ($p) => !is_string(action_args('postgres_terminate', null, ['pid' => $p]))) === [], 'and refuse a missing, low, negative, overlarge or non-numeric one');
$ok(action_args('apply_updates', 'x', ['unit' => 'a.service', 'pid' => 5]) === [null, null] && action_args('reboot', null, []) === [null, null], 'apply_updates and reboot carry no argument, whatever is sent');
$ok(action_args('restart_agent', 'helper', []) === [null, 'helper'] && is_string(action_args('restart_agent', null, [])) && is_string(action_args('restart_agent', 'Bad Name', [])), 'the agent verbs still need a well-formed agent');
$ok(is_string(action_args('run_shell', null, ['unit' => 'a.service'])) && is_string(action_args('', null, [])), 'an unknown verb is refused');

echo "== an action the kernel originates\n";
$pdo->prepare("INSERT INTO locations (name, kind, is_always_on, presence, last_seen_at, enrolled_at, enrolled_by_member_id, platform, siting, node_role)
               VALUES (:n, 'server', true, 'online', now(), now(), :by, 'physical_os', 'onsite', 'database-server')")->execute(['n' => "SMOKE NA {$run}", 'by' => (int) $admin['id']]);
$nodeId = (int) $pdo->lastInsertId();
$node = node_row($pdo, $nodeId);
$pdo->beginTransaction();
$a = action_create_kernel($pdo, $node, 'postgres_terminate', null, ['pid' => 4242], $admin, null, 'End the session of backend 4242 on SMOKE: idle for five hours.');
$pdo->commit();
$env = json_decode((string) $a['envelope'], true);
$ok(preg_match('/^a_[0-9a-f]{16}$/', (string) $a['id']) === 1 && $a['state'] === 'queued' && json_decode((string) $a['args'], true) === ['pid' => 4242] && $a['approval_request_id'] === null, 'queued with its arguments; no approval named for a super-admin\'s own');
$ok(($env['sig']['key'] ?? '') === 'coordinator' && ($env['originator']['principal'] ?? '') === 'human:' . (int) $admin['id'] && ($env['target']['node'] ?? '') === node_ref($node) && ($env['target']['action'] ?? '') === 'postgres_terminate',
    'its envelope is the coordinator\'s, names who asked, the node and the verb');
$v = envelope_verify($pdo, $env, null, false);
$ok($v['ok'] === true, 'the envelope verifies against the coordinator\'s key' . ($v['ok'] ? '' : " ({$v['reason']})"));
$p = present_action($a);
$ok($p['args'] === ['pid' => 4242] && $p['action'] === 'postgres_terminate' && array_key_exists('approval_request_id', $p), 'the action\'s answer carries its arguments');
$log = $pdo->query("SELECT source, after FROM activity_log WHERE action = 'estate.action.request' AND entity_id = {$nodeId} ORDER BY id DESC LIMIT 1")->fetch();
$ok($log !== false && $log['source'] === 'web' && str_contains((string) $log['after'], '4242'), 'the request is in the activity log with its arguments');

echo "== the node's inbox\n";
$items = inbox_take($pdo, $nodeId);
$mine = array_values(array_filter($items, static fn ($i) => $i['id'] === $a['id']));
$ok(count($mine) === 1 && $mine[0]['kind'] === 'action' && $mine[0]['action'] === 'postgres_terminate' && $mine[0]['args'] === ['pid' => 4242], 'the node is handed the verb and its arguments');
$r = inbox_result($pdo, $node, (string) $a['id'], ['result' => ['ok' => true, 'output' => 'pg_terminate_backend: t']]);
$done = action_row($pdo, (string) $a['id']);
$ok($done['state'] === 'completed' && str_contains((string) $done['result'], 'pg_terminate_backend'), 'its result completes the action (' . $done['state'] . ')');
$pdo->beginTransaction();
$b = action_create_kernel($pdo, $node, 'restart_unit', null, ['unit' => 'cups.service'], $admin, null, 'Restart cups on SMOKE.');
$pdo->commit();
inbox_take($pdo, $nodeId);
inbox_result($pdo, $node, (string) $b['id'], ['refused' => 'not_allowed', 'result' => ['ok' => false, 'error' => 'cups.service is not in this node\'s actions.units']]);
$ref = action_row($pdo, (string) $b['id']);
$ok($ref['state'] === 'refused' && $ref['reason'] === 'not_allowed', 'a unit the node does not list comes back refused by the node (' . $ref['state'] . ')');

echo "== the approval policy\n";
$pol = $pdo->query("SELECT * FROM approval_policies WHERE action_pattern = 'estate.node_action' AND applies_to = 'agents' AND active")->fetch();
$ok($pol !== false && (int) $pol['expires_after_hours'] === 24, 'an active policy pauses an agent\'s estate.node_action, expiring in a day');
$ok(approval_required($pdo, 'estate.node_action', null, null) === null, 'it does not pause a person (the super-admin runs the action directly)');
$reg = json_decode((string) file_get_contents(dirname(__DIR__) . '/mcp/action_registry.json'), true)['actions']['estate_node_action'] ?? null;
$ok(is_array($reg) && $reg['built'] === true && $reg['endpoint'] === '/estate/node-action.php' && $reg['log_event'] === 'estate.node_action'
    && array_column(array_filter($reg['params'], static fn ($x) => $x['required']), 'name') === ['location', 'action', 'reason'], 'the action registry carries estate_node_action: location, action and reason required');

echo "== the handler over HTTP: a super-admin directly, an agent through its approval\n";
$base = getenv('BOS_INTERNAL_URL') ?: 'http://127.0.0.1:8080';
putenv('PHP_INTERNAL_BASE=' . $base); $_ENV['PHP_INTERNAL_BASE'] = $base;
require_once dirname(__DIR__) . '/app/features/approvals/replay.php';
$post = static function (int $as, array $fields) use ($base): array {
    $ch = curl_init($base . '/estate/node-action.php');
    curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_POSTFIELDS => http_build_query($fields), CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 30,
        CURLOPT_HTTPHEADER => ['X-Action-Token: ' . mint_action_token($as, 120), 'Accept: application/json']]);
    $raw = curl_exec($ch); $code = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE); curl_close($ch);
    return [$code, is_string($raw) ? (json_decode($raw, true) ?: []) : []];
};
$dba = $pdo->query("SELECT p.member_id FROM agent_profiles p WHERE p.role_key = 'dba' AND p.status = 'active' ORDER BY p.member_id DESC LIMIT 1")->fetchColumn();
if ($dba === false) {
    echo "  (no database administrator hired here: bin/hire_watch_agents.php first; the HTTP checks are skipped)\n";
} else {
    $dba = (int) $dba;
    $count = static fn (): int => (int) $pdo->query("SELECT count(*) FROM estate_actions WHERE location_id = {$nodeId}")->fetchColumn();
    $n0 = $count();
    [$c, $j] = $post((int) $admin['id'], ['location' => $nodeId, 'action' => 'apply_updates', 'reason' => "SMOKE {$run}: security updates pending for four days"]);
    $ok($c === 200 && ($j['ok'] ?? null) === true && $count() === $n0 + 1 && ($j['action']['action'] ?? '') === 'apply_updates' && ($j['action']['state'] ?? '') === 'queued', "a super-admin's request is queued at once ({$c})");
    [$c, $j] = $post((int) $admin['id'], ['location' => $nodeId, 'action' => 'restart_unit', 'unit' => 'x.service; reboot', 'reason' => 'SMOKE']);
    $ok($c === 422 && $count() === $n0 + 1, "a malformed unit is 422 and queues nothing ({$c})");
    [$c, $j] = $post((int) $admin['id'], ['location' => $nodeId, 'action' => 'postgres_terminate', 'pid' => '4242']);
    $ok($c === 422 && $count() === $n0 + 1, "a request without a reason is 422 ({$c})");
    [$c, $j] = $post((int) $admin['id'], ['location' => 999999999, 'action' => 'reboot', 'reason' => 'SMOKE']);
    $ok($c === 422, "an unknown node is 422 ({$c})");
    $r0 = (int) $pdo->query("SELECT coalesce(max(id), 0) FROM approval_requests")->fetchColumn();
    [$c, $j] = $post($dba, ['location' => $nodeId, 'action' => 'postgres_terminate', 'pid' => '4242', 'reason' => "SMOKE {$run}: a transaction idle for five hours"]);
    $req = $pdo->query("SELECT * FROM approval_requests WHERE id > {$r0} AND action_key = 'estate_node_action' ORDER BY id DESC LIMIT 1")->fetch();
    $ok($c === 202 && ($j['status'] ?? '') === 'pending_approval' && $req !== false && $req['status'] === 'pending' && (int) $req['requested_by_member_id'] === $dba && $count() === $n0 + 1,
        "the database administrator's request pauses for approval and queues nothing ({$c})");
    $ok($req !== false && str_contains((string) $req['summary'], 'End the session of PostgreSQL backend 4242 on SMOKE NA') && (int) $req['approver_member_id'] > 0 && (int) $req['approver_member_id'] !== $dba,
        'the request says what and why in words, and names a person as its approver');
    if ($req !== false) {
        $_SESSION['member_id'] = (int) $req['approver_member_id'];
        db_apply_context($pdo);
        $full = find_approval_request($pdo, (int) $req['id']);
        $decided = decide_approval_request($pdo, (int) $req['id'], 'approved', (int) $req['approver_member_id'], 'proof');
        $out = replay_approved_request($full ?? $req);
        finish_approval_execution($pdo, (int) $req['id'], $out['ok'], $out['error']);
        $q = $pdo->query("SELECT * FROM estate_actions WHERE location_id = {$nodeId} ORDER BY created_at DESC LIMIT 1")->fetch();
        $ok($decided && $out['ok'] === true && $count() === $n0 + 2 && $q['action'] === 'postgres_terminate' && json_decode((string) $q['args'], true) === ['pid' => 4242]
            && (int) $q['approval_request_id'] === (int) $req['id'] && (int) $q['requested_by_member_id'] === $dba,
            'approved: the action is queued as the agent, with its pid and the approval that let it through' . ($out['ok'] ? '' : " ({$out['error']})"));
        $env2 = json_decode((string) $q['envelope'], true);
        $ok(($env2['originator']['principal'] ?? '') === 'agent:' . $dba && ($env2['sig']['key'] ?? '') === 'coordinator', "its envelope names the agent as the originator, signed by the coordinator");
        $out2 = replay_approved_request($full ?? $req);
        $ok($out2['ok'] !== true || $count() === $n0 + 2, 'replaying the same approval again queues nothing more');
        $_SESSION['member_id'] = (int) $admin['id'];
        db_apply_context($pdo);
    }
    $other = $pdo->query("SELECT p.member_id FROM agent_profiles p WHERE p.status = 'active' AND NOT EXISTS (SELECT 1 FROM department_members dm JOIN departments d ON d.id = dm.department_id WHERE dm.member_id = p.member_id AND d.system_key = 'it') LIMIT 1")->fetchColumn();
    if ($other !== false) {
        [$c, $j] = $post((int) $other, ['location' => $nodeId, 'action' => 'reboot', 'reason' => 'SMOKE']);
        $ok($c === 403, "an agent outside IT is refused ({$c})");
    }
}

node_retire($pdo, $nodeId);
$pdo->prepare("UPDATE locations SET name = name || ' retired' WHERE id = :id")->execute(['id' => $nodeId]);
echo $fails === 0 ? "\nPASS\n" : "\nFAIL ({$fails})\n";
exit($fails === 0 ? 0 : 1);
