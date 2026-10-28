<?php
declare(strict_types=1);
/**
 * Proof of the estate's nodes, the kernel half of Phase 13 slice 1 (db/188; maluos docs/phase13-slice1-nodes.md):
 * the five endpoints under /api/v1/estate/ and /api/v1/desks/estate on the internal port, the node code, the node
 * token's scope, the report, the health rules, the alerts, presence and the sweep, the operator's desk.
 *
 *   BOS_INTERNAL_URL=http://127.0.0.1:8089 php bin/test_estate_nodes.php
 *
 * Drives the endpoints the way maluctl estate does: a wrong code, a desk code, a code of the other kind, the code,
 * me, heartbeats with facts and reports (healthy, then everything wrong, then worse, then healthy), the offline
 * heartbeat, the sweep after backdating, the operator's desk reading the estate and a plain person's desk refused,
 * the same machine again, a taken name, leave and the 410 after it, a retirement from the estate's side. Everything
 * it makes is retired or revoked at the end; the SMOKE person is suspended.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/estate/nodes.php';
$pdo = db();
$admin = (int) $pdo->query("SELECT id FROM members WHERE business_role = 'super_admin' AND status = 'active' AND member_kind = 'human' ORDER BY id LIMIT 1")->fetchColumn();
$_SESSION['member_id'] = $admin;
db_apply_context($pdo);
$adminRow = find_member_by_id($pdo, $admin);
$fails = 0;
$ok = static function (bool $c, string $label) use (&$fails): void { if (!$c) { $fails++; } echo ($c ? '  ok   ' : '  FAIL ') . $label . "\n"; };
$run = date('md-His');
$call = static function (string $method, string $path, ?string $token, ?array $body = null): array {
    $ch = curl_init((getenv('BOS_INTERNAL_URL') ?: 'http://127.0.0.1:8080') . $path);
    $h = ['Accept: application/json', 'Content-Type: application/json'];
    if ($token !== null) { $h[] = 'Authorization: Bearer ' . $token; }
    curl_setopt_array($ch, [CURLOPT_CUSTOMREQUEST => $method, CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 30, CURLOPT_HTTPHEADER => $h]);
    if ($body !== null) { curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body)); }
    $raw = (string) curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $j = json_decode($raw, true) ?: [];
    return [$code, $j, $j['error']['code'] ?? null];
};
$pub = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJ' . substr(str_repeat(md5($run), 2), 0, 41) . ' host:smoke';
$facts = static fn (string $host, string $mid, string $kind = 'server') => ['surface' => 1, 'kind' => $kind, 'principal' => "host:{$host}", 'public_key' => $pub,
    'hostname' => $host, 'os_platform' => 'linux', 'os_release' => 'MaluOS 26.04.20261028', 'variant' => 'Server', 'app_version' => 'maluos-estate 0.1.1',
    'mcp_surface_version' => '1', 'cpu_cores' => 16, 'memory_mb' => 64000, 'storage_gb' => 900, 'machine_id' => $mid,
    'components' => ['postgresql-18', 'maludb-core', 'vault', 'gateway', 'agent']];
$healthy = static fn () => ['ts' => gmdate('Y-m-d\TH:i:s\Z'), 'boot_id' => 'b1', 'uptime_s' => 100,
    'units' => [['unit' => 'postgresql@18-main.service', 'active' => 'active', 'sub' => 'running', 'restarts' => 0], ['unit' => 'maluos-vault.service', 'active' => 'active', 'sub' => 'running', 'restarts' => 0],
                ['unit' => 'maluos-gateway.service', 'active' => 'active', 'sub' => 'running', 'restarts' => 1]],
    'agents' => [['name' => 'helpdesk', 'principal' => 'agent:helpdesk', 'active' => 'active', 'sub' => 'running', 'restarts' => 0]],
    'gateway' => ['ok' => true, 'version' => '0.4.3', 'backends' => [['name' => 'local', 'kind' => 'ollama_local', 'healthy' => true]], 'queue' => ['queued' => 0, 'running' => 1]],
    'vault' => ['ok' => true, 'alerts' => []], 'updates' => ['pending_count' => 3, 'security_count' => 1, 'reboot_required' => false],
    'disk' => [['mount' => '/', 'size_gb' => 95, 'used_pct' => 41]], 'memory' => ['total_mb' => 64000, 'available_mb' => 21000, 'swap_used_mb' => 0], 'load' => [0.8, 0.9, 1.1], 'cpu_cores' => 16, 'errors' => []];
$bad = static function (int $disk = 90) use ($healthy): array {
    $r = $healthy();
    $r['units'][0]['active'] = 'failed'; $r['units'][0]['sub'] = 'failed';
    $r['agents'][0] = ['name' => 'helpdesk', 'principal' => 'agent:helpdesk', 'active' => 'failed', 'sub' => 'failed', 'restarts' => 3];
    $r['vault']['alerts'] = [['id' => 9912, 'ts' => '2026-10-28T08:40:11', 'kind' => 'budget_exhausted', 'principal' => 'agent:helpdesk', 'title' => 'budget']];
    $r['updates']['reboot_required'] = true;
    $r['disk'][0]['used_pct'] = $disk;
    $r['memory']['available_mb'] = 1000;
    return $r;
};

// ---- fixtures: a SMOKE person, an ordinary user (no estate), and the admin as the operator ----
$email = "smoke-node-{$run}@example.invalid";
$pdo->prepare("INSERT INTO members (email, password_hash, display_name, role, business_role, email_verified_at, status) VALUES (:e, :h, :n, 'member', 'user', now(), 'active')")
    ->execute(['e' => $email, 'h' => hash_password(bin2hex(random_bytes(12)) . 'Aa1!'), 'n' => "SMOKE {$run} Node Person"]);
$person = (int) $pdo->lastInsertId();
$mid = str_repeat(substr(md5('node' . $run), 0, 8), 4);

echo "== the code\n";
$ok(estate_operator($adminRow) && !estate_operator(find_member_by_id($pdo, $person)), 'the super-admin is an operator, the person is not');
$c = desk_code_mint($pdo, $admin, '', $admin, 'server');
$ok(preg_match('/^[A-Z2-9]{4}-[A-Z2-9]{4}$/', $c['code']) === 1 && $pdo->query("SELECT kind FROM desk_enrollment_codes WHERE id = {$c['id']}")->fetchColumn() === 'server', "a server code ({$c['code']})");
$cd = desk_code_mint($pdo, $admin, '', $admin);
$ok(desk_code_take($pdo, $c['code'], ['desk']) === null && desk_code_take($pdo, $cd['code'], NODE_KINDS) === null && desk_code_take($pdo, $c['code'], NODE_KINDS) !== null, 'a code is taken only for its kind');
$ok(desk_code_take($pdo, $cd['code'], ['desk']) !== null, 'minting a server code did not expire the desk code');
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, ['code' => 'ZZZZ-ZZZZ'] + $facts('smoke-node', $mid));
$ok($st === 403 && $e === 'bad_code', "a wrong code is 403 bad_code ({$st} {$e})");
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, ['code' => $cd['code']] + $facts('smoke-node', $mid));
$ok($st === 403 && $e === 'bad_code', "a desk code cannot join a node ({$st} {$e})");
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, ['code' => $c['code']] + $facts('smoke-node', $mid, 'inference'));
$ok($st === 403 && $e === 'bad_code', "a server code refuses an inference join ({$st} {$e})");
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['code' => $c['code'], 'hostname' => 'x']);
$ok($st === 403 && $e === 'bad_code', "a node code cannot enrol a desk ({$st} {$e})");
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, ['surface' => 2, 'code' => $c['code']]);
$ok($st === 400 && $e === 'invalid', "an unknown surface is 400 invalid ({$st} {$e})");
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, ['code' => $c['code'], 'kind' => 'desk']);
$ok($st === 400 && $e === 'invalid', "kind desk on join is 400 ({$st})");
$ok($call('GET', '/api/v1/estate/join.php', null)[0] === 405, 'GET on join is 405');

echo "== join\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, ['code' => strtolower($c['code']), 'name' => "SMOKE {$run} db-1"] + $facts('smoke-node', $mid));
$ok($st === 201 && isset($j['token']) && str_starts_with($j['token'], 'node_'), "join answers 201 with a node token ({$st} {$e})");
$token = (string) ($j['token'] ?? ''); $nodeId = (int) ($j['node']['id'] ?? 0);
$ok(($j['node']['kind'] ?? '') === 'server' && $j['node']['name'] === "SMOKE {$run} db-1" && $j['node']['status'] === 'active' && $j['node']['presence'] === 'online' && $j['node']['last_report_at'] === null, 'the node: server, the given name, active, online, no report yet');
$ok(($j['enrolled_by']['member_id'] ?? 0) === $admin && $j['surface'] === 1 && $j['heartbeat_s'] === 60 && $j['report_s'] === 300 && $j['endpoints']['nodes'] === app_url('/api/v1/estate/nodes') && ($j['office']['url'] ?? '') === app_url('/'), 'enrolled_by, surface, heartbeat_s 60, report_s 300, the endpoints, the office');
$row = node_row($pdo, $nodeId);
$ok($row['hostname'] === 'smoke-node' && (int) $row['cpu_cores'] === 16 && $row['operating_system'] === 'MaluOS 26.04.20261028' && $row['machine_id'] === $mid && $row['external_ref'] === 'host:smoke-node' && $row['public_key'] === $pub && (int) $row['enrolled_by_member_id'] === $admin && $row['platform'] === 'physical_os' && $row['siting'] === 'onsite' && !empty($row['is_always_on']) && str_contains((string) $row['components'], 'gateway') && $row['owner_member_id'] === null, 'the facts, the key, the components, the operator and no owner on the location row');
$t = $pdo->query("SELECT scope, location_id, member_id FROM mcp_access_tokens WHERE token_hash = '" . hash('sha256', $token) . "'")->fetch();
$ok($t && $t['scope'] === 'node' && (int) $t['location_id'] === $nodeId && (int) $t['member_id'] === $admin && (int) $row['enrollment_token_id'] > 0, 'the token is scope node, bound to the node, the operator\'s; the node points at it');
$ok($call('POST', '/api/v1/estate/join.php', null, ['code' => $c['code']] + $facts('smoke-node', $mid))[0] === 403, 'the code cannot be used twice');
$ok((int) $pdo->query("SELECT count(*) FROM activity_log WHERE action = 'node.join' AND entity_id = {$nodeId} AND actor_member_id = {$admin} AND source = 'node'")->fetchColumn() === 1, 'node.join logged as the operator, source node');
$def = (string) $pdo->query("SELECT pg_get_functiondef('mcp_resolve_token(text)'::regprocedure)")->fetchColumn();
$ok(substr_count($def, "scope <> 'node'") === 2, 'mcp_resolve_token skips node tokens (the MCP servers never read a node as a person)');
$ok($call('GET', '/api/v1/desks/me.php', $token)[0] === 401 && $call('GET', '/api/v1/me.php', $token)[0] === 401, 'a node token is refused on the desks and person surfaces');

echo "== me, heartbeat, the report, the rules\n";
[$st, $j, $e] = $call('GET', '/api/v1/estate/me.php', $token);
$ok($st === 200 && $j['node']['id'] === $nodeId, "me answers the node ({$st})");
$ok($call('GET', '/api/v1/estate/me.php', 'node_notatoken')[0] === 401 && $call('GET', '/api/v1/estate/me.php', null)[0] === 401, 'an unknown token and no token are 401');
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $token, ['surface' => 1, 'presence' => 'online', 'app_version' => 'maluos-estate 0.1.2', 'facts' => ['hostname' => 'smoke-node', 'cpu_cores' => 32, 'memory_mb' => 128000, 'storage_gb' => 900], 'report' => $healthy()]);
$row = node_row($pdo, $nodeId);
$ok($st === 200 && $j['node']['last_report_at'] !== null && (int) $row['cpu_cores'] === 32 && $row['app_version'] === 'maluos-estate 0.1.2' && is_string($row['report']) && str_contains($row['report'], '"helpdesk"'), "heartbeat with a report: facts updated, the report stored, last_report_at set ({$st})");
$ok((int) $pdo->query("SELECT count(*) FROM estate_node_reports WHERE location_id = {$nodeId}")->fetchColumn() === 1 && (int) $pdo->query("SELECT count(*) FROM estate_alerts WHERE location_id = {$nodeId}")->fetchColumn() === 0, 'the report is kept; a healthy report raises nothing');
[$st, $j, $e] = $call('GET', '/api/v1/estate/nodes.php', $token);
$n = null; foreach ($j['nodes'] ?? [] as $x) { if ($x['id'] === $nodeId) { $n = $x; } }
$ok($st === 200 && $n !== null && $n['health'] === 'ok' && $n['summary'] === '3 updates pending (1 security)' && $n['units'] === ['up' => 3, 'down' => 0] && $n['agents']['running'] === 1 && $n['gateway']['backends_healthy'] === 1 && $n['disk_max_pct'] === 41 && $n['memory_available_pct'] === 33 && $n['load1'] == 0.8 && !isset($n['report']), 'nodes as the node: health ok, the summary, the counts, no report in the list');
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $token, ['presence' => 'online', 'report' => $bad()]);
$alerts = $pdo->query("SELECT kind, key, severity, title FROM estate_alerts WHERE location_id = {$nodeId} AND cleared_at IS NULL ORDER BY kind, key")->fetchAll();
$byKind = []; foreach ($alerts as $a) { $byKind[$a['kind'] . '/' . $a['key']] = $a; }
$ok($st === 200 && count($alerts) === 6 && $byKind['unit_down/postgresql@18-main.service']['severity'] === 'critical' && $byKind['agent_down/helpdesk']['title'] === 'agent helpdesk failed (3 restarts)'
    && $byKind['vault_alert/9912']['title'] === 'budget exhausted: agent:helpdesk' && isset($byKind['reboot_required/reboot']) && $byKind['disk_full//']['severity'] === 'warning' && $byKind['disk_full//']['title'] === 'disk / at 90 %' && $byKind['memory_low/memory']['severity'] === 'critical',
    'a bad report raises the six alerts of the rules with their severities (' . count($alerts) . ')');
[$st, $j, $e] = $call('GET', "/api/v1/estate/nodes.php?id={$nodeId}", $token);
$ok($st === 200 && $j['node']['health'] === 'critical' && $j['node']['summary'] === '1 unit down · 1 agent failed · 3 updates pending (1 security) · restart required · disk / at 90 %' && is_array($j['node']['report']) && count($j['alerts']) === 6, 'nodes/ID: critical, the summary, the full report, the open alerts');
$ok($call('GET', '/api/v1/estate/nodes.php?id=999999999', $token)[0] === 404, 'nodes/ID for no such node is 404');
$diskId = (int) $pdo->query("SELECT id FROM estate_alerts WHERE location_id = {$nodeId} AND kind = 'disk_full' AND cleared_at IS NULL")->fetchColumn();
$call('POST', '/api/v1/estate/heartbeat.php', $token, ['presence' => 'online', 'report' => $bad(97)]);
$d = $pdo->query("SELECT id, severity, title FROM estate_alerts WHERE location_id = {$nodeId} AND kind = 'disk_full' AND cleared_at IS NULL")->fetchAll();
$ok(count($d) === 1 && (int) $d[0]['id'] === $diskId && $d[0]['severity'] === 'critical' && $d[0]['title'] === 'disk / at 97 %', 'a disk at 90 % then 97 % is one alert, now critical');
$call('POST', '/api/v1/estate/heartbeat.php', $token, ['presence' => 'online', 'report' => $healthy()]);
[$st, $j, $e] = $call('GET', '/api/v1/estate/nodes.php', $token);
$n = null; foreach ($j['nodes'] as $x) { if ($x['id'] === $nodeId) { $n = $x; } }
$cleared = array_filter($j['alerts'], static fn ($a) => $a['node_id'] === $nodeId && $a['cleared_at'] !== null);
$ok((int) $pdo->query("SELECT count(*) FROM estate_alerts WHERE location_id = {$nodeId} AND cleared_at IS NULL")->fetchColumn() === 0 && $n['health'] === 'ok' && count($cleared) === 6, 'a healthy report clears them all; the answer still carries them (cleared in the last hour)');
$big = $healthy(); $big['blob'] = str_repeat('x', 33 * 1024);
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $token, ['presence' => 'online', 'report' => $big]);
$ok($st === 400 && $e === 'invalid', "a report over 32 KB is 400 invalid ({$st})");
$ok($call('POST', '/api/v1/estate/heartbeat.php', $token, ['presence' => 'away'])[0] === 400, 'a presence that is not online|offline is 400');
$ok((int) $pdo->query("SELECT count(*) FROM activity_log WHERE action LIKE 'node.heartbeat%'")->fetchColumn() === 0, 'heartbeats are not in the activity log');

echo "== presence\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $token, ['presence' => 'offline']);
$ok($st === 200 && $j['node']['presence'] === 'offline' && (int) $pdo->query("SELECT count(*) FROM estate_alerts WHERE location_id = {$nodeId} AND kind = 'node_offline' AND cleared_at IS NULL")->fetchColumn() === 1, 'the clean offline raises node_offline');
[$st, $j, $e] = $call('GET', "/api/v1/estate/nodes.php?id={$nodeId}", $token);
$ok($j['node']['health'] === 'offline' && $j['node']['summary'] === 'offline', 'health offline');
$call('POST', '/api/v1/estate/heartbeat.php', $token, ['presence' => 'online']);
$ok((int) $pdo->query("SELECT count(*) FROM estate_alerts WHERE location_id = {$nodeId} AND kind = 'node_offline' AND cleared_at IS NULL")->fetchColumn() === 0, 'back online clears it');
$pdo->exec("UPDATE locations SET last_seen_at = now() - interval '4 minutes' WHERE id = {$nodeId}");
$swept = node_presence_sweep($pdo);
$ok(in_array($nodeId, array_map('intval', array_column($swept, 'id')), true) && node_row($pdo, $nodeId)['presence'] === 'offline' && (int) $pdo->query("SELECT count(*) FROM estate_alerts WHERE location_id = {$nodeId} AND kind = 'node_offline' AND cleared_at IS NULL")->fetchColumn() === 1, 'the sweep marks a node silent for three minutes offline and raises node_offline');
$pdo->exec("UPDATE locations SET presence = 'online', last_seen_at = now() - interval '2 minutes' WHERE id = {$nodeId}");
$ok(!in_array($nodeId, array_map('intval', array_column(node_presence_sweep($pdo), 'id')), true), 'and leaves one heard from two minutes ago alone');
for ($i = 0; $i < 30; $i++) { $pdo->exec("INSERT INTO estate_node_reports (location_id, report) VALUES ({$nodeId}, '{}')"); }
node_presence_sweep($pdo);
$ok((int) $pdo->query("SELECT count(*) FROM estate_node_reports WHERE location_id = {$nodeId}")->fetchColumn() === NODE_REPORTS_KEPT, 'the sweep keeps 24 reports per node');

echo "== desks and the estate\n";
$cp = desk_code_mint($pdo, $person, '', $admin);
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['code' => $cp['code'], 'name' => "SMOKE {$run} person desk", 'hostname' => 'p-desk', 'machine_id' => str_repeat('cd', 16)]);
$pdesk = (int) ($j['desk']['id'] ?? 0); $ptok = (string) ($j['token'] ?? '');
$ok($st === 201 && array_key_exists('estate', $j['endpoints']) && $j['endpoints']['estate'] === null, 'a plain person\'s desk: endpoints.estate is null');
$ok($call('GET', '/api/v1/desks/estate.php', $ptok)[0] === 403 && $call('GET', '/api/v1/estate/nodes.php', $ptok)[0] === 403, 'and the estate answers it 403 on both paths');
$ca = desk_code_mint($pdo, $admin, '', $admin);
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['code' => $ca['code'], 'name' => "SMOKE {$run} operator desk", 'hostname' => 'op-desk', 'machine_id' => str_repeat('ef', 16)]);
$adesk = (int) ($j['desk']['id'] ?? 0); $atok = (string) ($j['token'] ?? '');
$ok($st === 201 && $j['endpoints']['estate'] === app_url('/api/v1/desks/estate'), 'the operator\'s desk: endpoints.estate is published');
[$st, $j, $e] = $call('GET', '/api/v1/desks/estate.php', $atok);
$kinds = []; foreach ($j['nodes'] ?? [] as $x) { $kinds[$x['id']] = $x; }
$ok($st === 200 && isset($kinds[$nodeId]) && $kinds[$nodeId]['kind'] === 'server' && isset($kinds[$adesk]) && $kinds[$adesk]['kind'] === 'desk' && $kinds[$adesk]['owner']['display_name'] === $adminRow['display_name'] && $kinds[$adesk]['health'] === 'ok' && isset($kinds[$pdesk]), 'desks/estate as the operator: the server and both desks, with owners and health');
$ok($call('GET', '/api/v1/estate/nodes.php', $atok)[0] === 200 && $call('GET', "/api/v1/desks/estate.php?id={$nodeId}", $atok)[1]['node']['id'] === $nodeId, 'estate/nodes and desks/estate?id= answer the operator\'s desk too');
$s = present_estate_for_settings($pdo);
$ok(count(array_filter($s['nodes'], static fn ($x) => $x['kind'] === 'desk')) === 0 && in_array($nodeId, array_column($s['nodes'], 'id'), true) && is_array($s['alerts']), 'Settings → Desks for an operator: the nodes without the desks, the open alerts');

echo "== the same machine again, a taken name, leave, retire\n";
$c2 = desk_code_mint($pdo, $admin, '', $admin, 'inference');
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, ['code' => $c2['code'], 'name' => "SMOKE {$run} gpu-1"] + $facts('smoke-node', $mid, 'inference'));
$ok($st === 201 && $j['node']['kind'] === 'inference' && (int) $j['node']['id'] !== $nodeId, "the same machine joining again as inference makes a new node ({$st})");
$node2 = (int) ($j['node']['id'] ?? 0); $token2 = (string) ($j['token'] ?? '');
$ok(node_row($pdo, $nodeId)['status'] === 'retired' && $call('GET', '/api/v1/estate/me.php', $token)[0] === 410 && (int) $pdo->query("SELECT count(*) FROM estate_alerts WHERE location_id = {$nodeId} AND cleared_at IS NULL")->fetchColumn() === 0, 'the old node is retired, its token answers 410, its alerts are cleared');
$c3 = desk_code_mint($pdo, $admin, '', $admin, 'server');
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, ['code' => $c3['code'], 'name' => "SMOKE {$run} gpu-1"] + $facts('other-node', str_repeat('ab', 16)));
$ok($st === 409 && $e === 'name_taken' && desk_code_take($pdo, $c3['code'], NODE_KINDS) !== null, "a taken node name is 409 name_taken and the code survives ({$st} {$e})");
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, ['code' => $c3['code']] + $facts("smoke-{$run}", str_repeat('ab', 16)));
$ok($st === 201 && $j['node']['name'] === "smoke-{$run}", "a nameless join is named after the hostname ({$j['node']['name']})");
$node3 = (int) $j['node']['id']; $token3 = (string) $j['token'];
[$st, $j, $e] = $call('POST', '/api/v1/estate/leave.php', $token2);
$ok($st === 200 && $j['node']['status'] === 'retired' && node_row($pdo, $node2)['status'] === 'retired' && $call('GET', '/api/v1/estate/me.php', $token2)[0] === 410, "leave retires the node and its token answers 410 ({$st})");
$ok((int) $pdo->query("SELECT count(*) FROM mcp_access_tokens WHERE scope = 'node' AND location_id = {$node2} AND revoked_at IS NULL")->fetchColumn() === 0 && (int) $pdo->query("SELECT count(*) FROM activity_log WHERE action = 'node.leave' AND entity_id = {$node2} AND actor_member_id = {$admin}")->fetchColumn() === 1, 'the token is revoked; node.leave logged as the operator');
node_retire($pdo, $node3);   // what locations/retire.php does for a node, from the estate's side
$ok($call('POST', '/api/v1/estate/heartbeat.php', $token3, ['presence' => 'online'])[0] === 410, 'a node retired from the estate: its heartbeat gets 410');
[$st, $j, $e] = $call('GET', '/api/v1/desks/estate.php', $atok);
$ok(!in_array($nodeId, array_column($j['nodes'], 'id'), true) && !in_array($node2, array_column($j['nodes'], 'id'), true), 'retired nodes are gone from the estate');

// ---- cleanup ----
desk_retire($pdo, $pdesk); desk_retire($pdo, $adesk);
$pdo->exec("UPDATE members SET status = 'suspended' WHERE id = {$person}");
echo "\n" . ($fails === 0 ? 'PASS' : "FAIL ({$fails})") . "\n";
exit($fails === 0 ? 0 : 1);
