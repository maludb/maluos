<?php
declare(strict_types=1);
/**
 * Proof of federated memory, the kernel half of Phase 13 slice 4 (db/192; maluos docs/phase13-slice4-memory.md):
 * the memory endpoints named at join and enrol, the facts a heartbeat carries and the version they bump, the holders each
 * member is published scope by scope (never itself, never a desk to another desk, the defaults: org for everyone, a desk
 * its owner's departments, a server every department), the peers a holder is given, the policy's precedence (node > dept
 * > kind > org, holder-specific over any, scope-specific over any, deny over allow), the flags on heartbeats, the office
 * as a holder (a desk's query as its owner, a node's with its envelope: the authority, the classification, replay, the
 * rate; the claim shape from a stubbed recall), the settings presenter, and what a leaving node takes with it.
 *
 *   BOS_INTERNAL_URL=http://127.0.0.1:8089 php bin/test_estate_memory.php
 *
 * Re-runnable; everything it makes is named SMOKE and retired at the end.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/estate/nodes.php';
$pdo = db();
$admin = (int) $pdo->query("SELECT id FROM members WHERE business_role = 'super_admin' AND status = 'active' AND member_kind = 'human' ORDER BY id LIMIT 1")->fetchColumn();
$_SESSION['member_id'] = $admin;
db_apply_context($pdo);
$fails = 0;
$ok = static function (bool $c, string $label) use (&$fails): void { if (!$c) { $fails++; } echo ($c ? '  ok   ' : '  FAIL ') . $label . "\n"; };
$run = date('md-His');
$base = getenv('BOS_INTERNAL_URL') ?: 'http://127.0.0.1:8080';
$call = static function (string $method, string $path, ?string $token, ?array $body = null) use ($base): array {
    $ch = curl_init($base . $path);
    $h = ['Accept: application/json', 'Content-Type: application/json'];
    if ($token !== null) { $h[] = 'Authorization: Bearer ' . $token; }
    curl_setopt_array($ch, [CURLOPT_CUSTOMREQUEST => $method, CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 60, CURLOPT_HTTPHEADER => $h]);
    if ($body !== null) { curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body)); }
    $raw = (string) curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $j = json_decode($raw, true) ?: [];
    return [$code, $j, $j['error']['code'] ?? null];
};
$wg = static fn () => base64_encode(random_bytes(32));
$sorted = static function (array $xs): array { sort($xs); return $xs; };
$mk = static fn (string $kind) => desk_code_mint($pdo, $admin, '', $admin, $kind)['code'];
$releaseSmoke = static function () use ($pdo, $admin): void {
    $pdo->exec("UPDATE locations SET overlay_address_freed_at = now() - interval '31 days' WHERE name LIKE 'SMOKE %' AND status = 'retired' AND overlay_address IS NOT NULL");
    $pdo->exec("DELETE FROM estate_memory_policy WHERE note LIKE 'SMOKE %'");
    $pdo->exec("DELETE FROM department_members WHERE member_id = {$admin} AND department_id IN (SELECT id FROM departments WHERE name LIKE 'SMOKE %')");
    $pdo->exec("DELETE FROM departments WHERE name LIKE 'SMOKE %'");
};
$releaseSmoke();
foreach ($pdo->query("SELECT id, kind FROM locations WHERE name LIKE 'SMOKE %' AND status = 'active'")->fetchAll() as $left) {
    $left['kind'] === 'desk' ? desk_retire($pdo, (int) $left['id']) : node_retire($pdo, (int) $left['id']);
}
$releaseSmoke();
// the admin (every desk's owner here) joins a SMOKE department: dept:D is the one departmental scope a desk may read by default
$pdo->prepare('INSERT INTO departments (name) VALUES (:n)')->execute(['n' => "SMOKE {$run} dept"]);
$deptId = (int) $pdo->query("SELECT id FROM departments WHERE name = 'SMOKE {$run} dept'")->fetchColumn();
$pdo->prepare('INSERT INTO department_members (department_id, member_id, is_primary) VALUES (:d, :m, false)')->execute(['d' => $deptId, 'm' => $admin]);
$otherDept = (int) $pdo->query("SELECT id FROM departments WHERE archived_at IS NULL AND id <> {$deptId} ORDER BY id LIMIT 1")->fetchColumn();
$ok($deptId > 0 && $otherDept > 0, "the admin is in SMOKE dept:{$deptId}; dept:{$otherDept} is another department");
$facts = static fn (array $held, array $shared, string $maxc = 'internal', int $port = 11437) => [
    'scopes' => array_map(static fn ($s) => ['scope' => $s, 'count' => 3, 'updated_at' => '2026-10-31T12:00:00Z', 'kinds' => ['note' => 2, 'summary' => 1]], $held),
    'shared' => $shared, 'max_classification' => $maxc, 'port' => $port, 'api_version' => 1];
// keys and envelopes, signed the way the hosts sign (slice 2)
$nodePair = sodium_crypto_sign_keypair(); $nodePub = ssh_ed25519_line(sodium_crypto_sign_publickey($nodePair), 'node');
$otherPair = sodium_crypto_sign_keypair();
$sign = static function (array $env, string $keyNode, string $secret): array {
    $env['sender']['node'] = $keyNode;
    $env['sig'] = ['alg' => 'ed25519', 'key' => $keyNode, 'value' => base64_encode(sodium_crypto_sign_detached(envelope_canonical($env), $secret))];
    return $env;
};
$envelope = static function (string $originator, string $onode, array $scopes, string $cls = 'internal', int $life = 120): array {
    $now = time();
    return ['v' => 1, 'id' => envelope_new_id(), 'issued_at' => gmdate('Y-m-d\TH:i:s\Z', $now), 'expires_at' => gmdate('Y-m-d\TH:i:s\Z', $now + $life), 'nonce' => bin2hex(random_bytes(8)),
            'originator' => ['principal' => $originator, 'kind' => str_starts_with($originator, 'agent:') ? 'agent' : 'human', 'node' => $onode],
            'sender' => ['principal' => $originator, 'node' => $onode],
            'chain' => [['principal' => $originator, 'node' => $onode, 'ts' => gmdate('Y-m-d\TH:i:s\Z', $now), 'task_id' => 't_smoke']],
            'target' => ['node' => 'coordinator'], 'purpose' => 'memory',
            'authority' => ['scopes' => $scopes, 'classification' => $cls, 'budget' => ['usd' => 0, 'calls' => 0]]];
};

echo "== three members join: the hub (a server), an HR server (the holder), a desk and a laptop\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, ['surface' => 1, 'kind' => 'server', 'code' => $mk('server'), 'name' => "SMOKE {$run} hub", 'principal' => 'host:hub', 'hostname' => 'hub',
    'os_release' => 'MaluOS 26.04', 'app_version' => 'maluos-estate 0.5.0', 'cpu_cores' => 4, 'memory_mb' => 8000, 'storage_gb' => 100, 'machine_id' => str_repeat(substr(md5('hub' . $run), 0, 8), 4),
    'overlay_public_key' => $wg(), 'overlay_hub' => ['endpoint' => 'hub.example.test:51820']]);
$ok($st === 201 && ($j['node']['id'] ?? 0) > 0, "the hub joined ({$j['node']['id']})");
$hubId = (int) $j['node']['id']; $hubTok = (string) $j['token']; $hubRef = "server:{$hubId}";
$ok(($j['endpoints']['memory'] ?? '') === app_url('/api/v1/estate/memory') && ($j['endpoints']['memory_peers'] ?? '') === app_url('/api/v1/estate/memory/peers'), 'the join answer names memory and memory_peers');
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, ['surface' => 1, 'kind' => 'server', 'code' => $mk('server'), 'name' => "SMOKE {$run} hr", 'principal' => 'host:hr', 'hostname' => 'hr',
    'machine_id' => str_repeat(substr(md5('hr' . $run), 0, 8), 4), 'overlay_public_key' => $wg(), 'public_key' => $nodePub]);
$ok($st === 201 && ($j['overlay']['role'] ?? '') === 'spoke', 'the HR server joined as a spoke with its signing key');
$hrId = (int) $j['node']['id']; $hrTok = (string) $j['token']; $hrRef = "server:{$hrId}"; $hrAddr = (string) $j['overlay']['address'];
$cd = desk_code_mint($pdo, $admin, '', $admin, 'desk');
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['surface' => 1, 'code' => $cd['code'], 'name' => "SMOKE {$run} desk", 'hostname' => 'desk', 'machine_id' => str_repeat(substr(md5('desk' . $run), 0, 8), 4), 'overlay_public_key' => $wg()]);
$ok($st === 201 && ($j['desk']['id'] ?? 0) > 0 && ($j['endpoints']['memory'] ?? '') === app_url('/api/v1/desks/memory') && ($j['endpoints']['memory_peers'] ?? '') === app_url('/api/v1/estate/memory/peers')
    && ($j['endpoints']['memory_mcp'] ?? '') === app_url('/mcp/memory'),
    'the desk enrolled; endpoints.memory is the desks endpoint (null no more), memory_peers the estate one, memory_mcp the proxied Memory MCP (db/193)');
$deskId = (int) $j['desk']['id']; $deskTok = (string) $j['token']; $deskRef = "desk:{$deskId}";
$cd = desk_code_mint($pdo, $admin, '', $admin, 'desk');
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['surface' => 1, 'code' => $cd['code'], 'name' => "SMOKE {$run} laptop", 'hostname' => 'laptop', 'machine_id' => str_repeat(substr(md5('lap' . $run), 0, 8), 4), 'overlay_public_key' => $wg()]);
$lapId = (int) $j['desk']['id']; $lapTok = (string) $j['token']; $lapRef = "desk:{$lapId}";
$ok($st === 201, 'a second desk (a laptop) enrolled');
$ok((int) $pdo->query("SELECT memory_seen_version FROM locations WHERE id = {$hubId}")->fetchColumn() === (int) memory_settings($pdo)['version'], 'join marks the versions heard');

echo "== the facts ride the heartbeat and bump the version only when the published view changes\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $hrTok, ['surface' => 1, 'presence' => 'online', 'memory' => $facts(["dept:{$deptId}", "dept:{$otherDept}", 'org', 'agent:hr'], ["dept:{$deptId}", "dept:{$otherDept}", 'org'])]);
$ok($st === 200 && ($j['memory_changed'] ?? null) === true && array_key_exists('memory_peers_changed', $j), 'the HR server\'s first facts: stored, memory_changed true, memory_peers_changed answered');
$row = $pdo->query("SELECT * FROM estate_memory WHERE location_id = {$hrId}")->fetch();
$held = array_column(json_decode($row['scopes'], true), 'scope');
$ok($row !== false && $row['port'] === 11437 && count($held) === 3 && !in_array('agent:hr', $held, true) && json_decode($row['shared'], true) === $sorted(["dept:{$deptId}", "dept:{$otherDept}", 'org']), 'estate_memory holds the three shareable scopes (the personal one dropped), the shared list, the port');
$f2 = $facts(["dept:{$deptId}", "dept:{$otherDept}", 'org'], ["dept:{$deptId}", "dept:{$otherDept}", 'org']); $f2['scopes'][0]['count'] = 9;
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $hrTok, ['surface' => 1, 'presence' => 'online', 'memory' => $f2]);
$ok($st === 200 && $j['memory_changed'] === false && (int) json_decode((string) $pdo->query("SELECT scopes FROM estate_memory WHERE location_id = {$hrId}")->fetchColumn(), true)[0]['count'] === 9, 'the counts change without a bump; the live numbers are kept');
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $hrTok, ['surface' => 1, 'presence' => 'online', 'memory' => $facts(["dept:{$deptId}", "dept:{$otherDept}", 'org'], ["dept:{$deptId}", 'org'])]);
$ok($st === 200 && $j['memory_changed'] === true, 'a scope leaving the shared list bumps the version: memory_changed true');
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $hrTok, ['surface' => 1, 'presence' => 'online', 'memory' => ['scopes' => [['scope' => 'org', 'count' => 1, 'kinds' => ['x' => str_repeat('y', 9000)]]]]]);
$ok($st === 400 && $e === 'invalid', 'facts over 8 KB are refused invalid');
$call('POST', '/api/v1/estate/heartbeat.php', $hrTok, ['surface' => 1, 'presence' => 'online', 'memory' => $facts(["dept:{$deptId}", "dept:{$otherDept}", 'org'], ["dept:{$deptId}", "dept:{$otherDept}", 'org'])]);
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $hubTok, ['surface' => 1, 'presence' => 'online', 'memory' => $facts(['org'], ['org'], 'restricted')]);
$ok($st === 200, 'the hub reports and shares org with a restricted ceiling of its own');
[$st, $j, $e] = $call('POST', '/api/v1/desks/heartbeat.php', $deskTok, ['surface' => 1, 'presence' => 'online', 'memory' => $facts(["dept:{$deptId}", 'user:ed'], ["dept:{$deptId}"])]);
$ok($st === 200 && array_key_exists('memory_changed', $j) && array_key_exists('memory_peers_changed', $j), 'a desk heartbeat carries facts and answers the two flags');

echo "== what each member is published\n";
[$st, $j, $e] = $call('GET', '/api/v1/desks/memory.php', $deskTok);
$byNode = []; foreach ($j['holders'] ?? [] as $h) { $byNode[$h['node']] = $h; }
$ok($st === 200 && isset($byNode[$hrRef], $byNode[$hubRef]) && !isset($byNode[$deskRef]) && $j['fanout_max'] === 8 && $j['rate_per_min'] === 30 && $j['refresh_s'] === 3600, 'the desk: the HR server and the hub, never itself; the fan-out, the rate, the refresh');
$hrScopes = array_column($byNode[$hrRef]['scopes'] ?? [], null, 'scope');
$ok(isset($hrScopes["dept:{$deptId}"], $hrScopes['org']) && !isset($hrScopes["dept:{$otherDept}"]) && $hrScopes['org']['classification_max'] === 'internal' && $hrScopes['org']['replicate'] === false && $hrScopes["dept:{$deptId}"]['count'] === 3,
    'the default: the desk reads org and its owner\'s department from the HR server, not the other department; the ceiling internal, the counts');
$ok($byNode[$hrRef]['address'] === $hrAddr && $byNode[$hrRef]['port'] === 11437 && str_ends_with($byNode[$hrRef]['name'], '-hr') && $byNode[$hrRef]['max_classification'] === 'internal', 'a holder row: the overlay address and port, the overlay label, the host\'s own ceiling');
$office = array_column($j['office']['scopes'] ?? [], null, 'scope');
$ok(($j['office']['query'] ?? '') === app_url('/api/v1/desks/memory/query') && isset($office['self'], $office['org'], $office["dept:{$deptId}"]) && !isset($office["dept:{$otherDept}"]) && $office["dept:{$deptId}"]['label'] === "SMOKE {$run} dept",
    'the office\'s own scopes for the desk: self, org and the owner\'s department with its name; the query URL');
[$st, $j, $e] = $call('GET', '/api/v1/estate/memory.php', $hubTok);
$byNode = []; foreach ($j['holders'] ?? [] as $h) { $byNode[$h['node']] = $h; }
$hrScopes = array_column($byNode[$hrRef]['scopes'] ?? [], null, 'scope');
$ok($st === 200 && isset($byNode[$hrRef], $byNode[$deskRef]) && !isset($byNode[$hubRef]) && isset($hrScopes["dept:{$deptId}"], $hrScopes["dept:{$otherDept}"], $hrScopes['org']),
    'the hub (a server): every department from the HR server, and the desk\'s shared department; never itself');
$ok(($byNode[$deskRef]['scopes'][0]['scope'] ?? '') === "dept:{$deptId}" && ($j['office']['query'] ?? '') === app_url('/api/v1/estate/memory/query') && !isset(array_column($j['office']['scopes'], null, 'scope')['self']),
    'a server is given the desk\'s departmental scope; the office\'s scopes for a node carry no self');
[$st, $j, $e] = $call('GET', '/api/v1/desks/memory.php', $lapTok);
$ok($st === 200 && !in_array($deskRef, array_column($j['holders'], 'node'), true) && in_array($hrRef, array_column($j['holders'], 'node'), true), 'decision 5: the laptop is not given the desk (a desk holder never serves another desk)');
[$st, $j, $e] = $call('GET', '/api/v1/estate/memory.php', $deskTok);
$ok($st === 200 && in_array($hrRef, array_column($j['holders'], 'node'), true), 'the estate endpoint takes a desk token too');
[$st, $j, $e] = $call('GET', '/api/v1/estate/memory.php', null);
$ok($st === 401, 'the holders need a token');
[$st, $j, $e] = $call('GET', '/api/v1/desks/memory.php?all=1', $deskTok);
$byNode = []; foreach ($j['holders'] ?? [] as $h) { $byNode[$h['node']] = $h; }
$hrScopes = array_column($byNode[$hrRef]['scopes'] ?? [], null, 'scope');
$ok($st === 200 && isset($hrScopes["dept:{$otherDept}"]) && $hrScopes["dept:{$otherDept}"]['allowed'] === false && $hrScopes['org']['allowed'] === true, 'an operator\'s desk with ?all=1: every shared scope, each with allowed');
$pdo->exec("UPDATE locations SET presence = 'offline' WHERE id = {$hrId}");
[$st, $j, $e] = $call('GET', '/api/v1/desks/memory.php', $deskTok);
$ok(!in_array($hrRef, array_column($j['holders'], 'node'), true), 'an offline holder is not published');
$pdo->exec("UPDATE locations SET presence = 'online' WHERE id = {$hrId}");
$call('POST', '/api/v1/estate/heartbeat.php', $hubTok, ['surface' => 1, 'presence' => 'online', 'memory' => $facts(['org'], [])]);
[$st, $j, $e] = $call('GET', '/api/v1/desks/memory.php', $deskTok);
$ok(!in_array($hubRef, array_column($j['holders'], 'node'), true), 'sharing nothing: the hub leaves the desk\'s list');
$call('POST', '/api/v1/estate/heartbeat.php', $hubTok, ['surface' => 1, 'presence' => 'online', 'memory' => $facts(['org'], ['org'], 'restricted')]);

echo "== the peers a holder is given\n";
[$st, $j, $e] = $call('GET', '/api/v1/estate/memory.php?sub=peers', $hrTok);
$byNode = []; foreach ($j['peers'] ?? [] as $p) { $byNode[$p['node']] = $p; }
$ok($st === 200 && isset($byNode[$deskRef], $byNode[$lapRef], $byNode[$hubRef]) && !isset($byNode[$hrRef]) && $j['shared'] === $sorted(["dept:{$deptId}", "dept:{$otherDept}", 'org']) && $j['keys'] === app_url('/api/v1/estate/keys'),
    'the HR server\'s peers: the desk, the laptop and the hub, never itself; its shared list; where the keys are');
$deskScopes = array_column($byNode[$deskRef]['scopes'] ?? [], 'scope'); $hubScopes = array_column($byNode[$hubRef]['scopes'] ?? [], 'scope');
sort($deskScopes); sort($hubScopes);
$ok($deskScopes === $sorted(["dept:{$deptId}", 'org']) && $hubScopes === $sorted(["dept:{$deptId}", "dept:{$otherDept}", 'org']) && ($byNode[$deskRef]['scopes'][0]['classification_max'] ?? '') === 'internal', 'each peer carries the scopes it may ask and its ceilings: the desk two, the hub three');
$ok(array_key_exists('public_key', $byNode[$hubRef]) && $byNode[$hubRef]['public_key'] === null && ($byNode[$hrRef]['public_key'] ?? null) === null, 'each peer row carries its signing key when it registered one (none of these did: null)');
[$st, $j, $e] = $call('GET', '/api/v1/estate/memory.php?sub=peers', $deskTok);
$ok($st === 200 && !in_array($lapRef, array_column($j['peers'], 'node'), true) && in_array($hubRef, array_column($j['peers'], 'node'), true) && in_array($hrRef, array_column($j['peers'], 'node'), true), 'the desk\'s peers (a desk token): the servers, never the other desk');
[$st, $j, $e] = $call('GET', '/api/v1/estate/memory.php?sub=peers', $lapTok);
$ok($st === 200 && $j['peers'] === [] && $j['shared'] === [], 'a member that shares nothing has no peers');

echo "== the policy: precedence, the flags, the ceilings, replication\n";
$r1 = memory_rule_add($pdo, ['subject' => 'kind:desk', 'scope' => "dept:{$deptId}", 'holder_location_id' => $hrId, 'allow' => false, 'note' => "SMOKE {$run} no desks on hr dept"], $admin);
[$st, $j, $e] = $call('GET', '/api/v1/desks/memory.php', $deskTok);
$byNode = []; foreach ($j['holders'] ?? [] as $h) { $byNode[$h['node']] = $h; }
$ok(array_column($byNode[$hrRef]['scopes'] ?? [], 'scope') === ['org'], 'deny kind:desk on the HR server\'s department scope: the desk keeps org there, loses the department');
[$st, $j, $e] = $call('GET', '/api/v1/estate/memory.php?sub=peers', $hrTok);
$byNode = []; foreach ($j['peers'] ?? [] as $p) { $byNode[$p['node']] = $p; }
$ok(array_column($byNode[$deskRef]['scopes'] ?? [], 'scope') === ['org'], 'and the HR server lists the desk as a peer for org only');
[$st, $j, $e] = $call('POST', '/api/v1/desks/heartbeat.php', $deskTok, ['surface' => 1, 'presence' => 'online']);
$ok($st === 200 && $j['memory_changed'] === false && $j['memory_peers_changed'] === true, 'the rule bumped both versions: the desk\'s next heartbeat says memory_peers_changed (its read of the holders a moment ago marked those heard)');
[$st, $j, $e] = $call('POST', '/api/v1/desks/heartbeat.php', $deskTok, ['surface' => 1, 'presence' => 'online']);
$ok($st === 200 && $j['memory_changed'] === false && $j['memory_peers_changed'] === false, 'heard once, the flags fall');
$r2 = memory_rule_add($pdo, ['subject' => "node:{$deskId}", 'scope' => '*', 'holder_location_id' => $hrId, 'allow' => true, 'max_classification' => 'restricted', 'replicate' => true, 'priority' => 5, 'note' => "SMOKE {$run} this desk may"], $admin);
[$st, $j, $e] = $call('GET', '/api/v1/desks/memory.php', $deskTok);
$byNode = []; foreach ($j['holders'] ?? [] as $h) { $byNode[$h['node']] = $h; }
$hrScopes = array_column($byNode[$hrRef]['scopes'] ?? [], null, 'scope');
$ok(isset($hrScopes["dept:{$deptId}"], $hrScopes["dept:{$otherDept}"], $hrScopes['org']) && $hrScopes['org']['classification_max'] === 'restricted' && $hrScopes['org']['replicate'] === true && $hrScopes['org']['priority'] === 5,
    'a node rule for any scope beats the kind rule: the desk has every scope of the HR server at restricted, replicate on, priority 5');
$r3 = memory_rule_add($pdo, ['subject' => "node:{$deskId}", 'scope' => "dept:{$deptId}", 'holder_location_id' => $hrId, 'allow' => false, 'note' => "SMOKE {$run} but not that one"], $admin);
[$st, $j, $e] = $call('GET', '/api/v1/desks/memory.php', $deskTok);
$byNode = []; foreach ($j['holders'] ?? [] as $h) { $byNode[$h['node']] = $h; }
$hrScopes = array_column($byNode[$hrRef]['scopes'] ?? [], null, 'scope');
$ok(!isset($hrScopes["dept:{$deptId}"]) && isset($hrScopes['org']), 'a rule naming the scope beats one for any at the same depth');
$r4 = memory_rule_add($pdo, ['subject' => 'org', 'scope' => '*', 'holder_location_id' => null, 'allow' => false, 'note' => "SMOKE {$run} nobody"], $admin);
[$st, $j, $e] = $call('GET', '/api/v1/estate/memory.php', $hubTok);
$ok($j['holders'] === [] && $j['office']['scopes'] === [], 'deny org on any scope at any holder: the hub is given nothing, the office included');
[$st, $j, $e] = $call('GET', '/api/v1/desks/memory.php', $deskTok);
$ok(count($j['holders']) === 1 && $j['holders'][0]['node'] === $hrRef && array_column($j['office']['scopes'], 'scope') === ['self'], 'but the desk\'s node rule still admits it to the HR server (more specific than org); at the office only self');
$ok(memory_rule_delete($pdo, (int) $r4['id']) && memory_rule_delete($pdo, (int) $r3['id']) && memory_rule_delete($pdo, (int) $r2['id']) && memory_rule_delete($pdo, (int) $r1['id']), 'the rules removed');
try { memory_rule_add($pdo, ['subject' => 'org', 'scope' => 'agent:x', 'note' => "SMOKE {$run} bad"], $admin); $ok(false, 'a personal scope in a rule is refused'); }
catch (InvalidArgumentException $ex) { $ok(true, 'a personal scope in a rule is refused: ' . $ex->getMessage()); }
[$st, $j, $e] = $call('GET', '/api/v1/estate/memory.php', $hubTok);
$ok(in_array($hrRef, array_column($j['holders'], 'node'), true), 'the default is back');

echo "== the office as a holder: a desk's query as its owner\n";
[$st, $j, $e] = $call('POST', '/api/v1/desks/memory.php?sub=query', $deskTok, ['scopes' => ["dept:{$otherDept}"], 'query' => 'forklift training']);
$ok($st === 403 && $e === 'forbidden', 'a department the owner is not in: forbidden');
[$st, $j, $e] = $call('POST', '/api/v1/desks/memory.php?sub=query', $deskTok, ['scopes' => ['org'], 'query' => 'forklift training', 'classification' => 'restricted']);
$ok($st === 403 && $e === 'classification', 'restricted above the internal ceiling: classification');
[$st, $j, $e] = $call('POST', '/api/v1/desks/memory.php?sub=query', $deskTok, ['scopes' => ['agent:hr'], 'query' => 'x']);
$ok($st === 400 && $e === 'invalid', 'a personal scope is not a query scope: invalid');
[$st, $j, $e] = $call('POST', '/api/v1/desks/memory.php?sub=query', $deskTok, ['scopes' => ['org'], 'query' => '']);
$ok($st === 400 && $e === 'invalid', 'an empty query: invalid');
[$st, $j, $e] = $call('POST', '/api/v1/desks/memory.php?sub=query', $deskTok, ['scopes' => ['org', "dept:{$deptId}", 'self'], 'query' => 'forklift training', 'limit' => 5]);
$ok(in_array($st, [200, 503], true) && ($st === 200 ? ($j['holder'] === 'coordinator' && is_array($j['claims']) && $j['scopes_asked'] === ['org', "dept:{$deptId}", 'self']) : $e === 'memory_unavailable'),
    "org, the owner's department and self: answered by the office (" . ($st === 200 ? count($j['claims']) . ' claims' : 'MaluDB unavailable here: 503 memory_unavailable') . ')');
$ok((int) $pdo->query("SELECT count(*) FROM activity_log WHERE action = 'memory.query' AND entity_type = 'locations' AND entity_id = {$deskId}")->fetchColumn() === 1, 'one activity row per answered query, none for the refusals');
$row = $pdo->query("SELECT after FROM activity_log WHERE action = 'memory.query' AND entity_type = 'locations' AND entity_id = {$deskId} ORDER BY id DESC LIMIT 1")->fetchColumn();
$after = json_decode((string) $row, true) ?: [];
$ok(($after['scopes'] ?? null) === ['org', "dept:{$deptId}", 'self'] && !isset($after['query']) && !isset($after['text']), 'the row carries the scopes asked and never the text');
// the claim shape, from a stubbed recall (MaluDB is not needed for the projection)
$ctx = ['desk' => desk_row($pdo, $deskId), 'member' => find_member_by_id($pdo, $admin)];
$stub = static fn (array $ns, string $q, int $limit) => [['results' => [
    ['source_text' => 'Alex completed forklift training on 2026-09-01', 'namespace' => "dept:{$deptId}", 'subject_name' => 'Alex', 'similarity' => 0.91, 'confidence' => 0.9, 'document_id' => 118, 'payload' => ['certificate' => 'FL-2231']],
    ['source_text' => 'The organisation closes at 17:00 on Fridays', 'namespace' => 'org', 'subject_name' => null, 'similarity' => 0.4]]], null];
[$status, $ans] = memory_office_query($pdo, $ctx, ['scopes' => ['org', "dept:{$deptId}"], 'query' => 'forklift', 'limit' => 10], $stub);
$c = $ans['claims'][0] ?? [];
$ok($status === 200 && count($ans['claims']) === 2 && $c['text'] === 'Alex completed forklift training on 2026-09-01' && $c['scope'] === "dept:{$deptId}" && $c['confidence'] === 0.9 && $c['source'] === ['node' => 'coordinator', 'object' => 'memory', 'id' => 118, 'ref' => 'Alex']
    && $c['holder'] === 'coordinator' && $c['rank'] === 1 && $c['sensitivity'] === 'internal' && !isset($c['payload']) && !isset($c['similarity']) && array_key_exists('confidence', $ans['claims'][1]) && $ans['claims'][1]['confidence'] === null,
    'a claim: text, scope, confidence, source with the office as its node, holder, rank; no payload, no similarity; confidence null when the writer gave none');
$ok($ans['scopes_read'] === ["dept:{$deptId}", 'org'] && $ans['count'] === 2 && $ans['truncated'] === false, 'scopes_read is what the claims came from');
[$status, $ans] = memory_office_query($pdo, $ctx, ['scopes' => ['org'], 'query' => 'forklift', 'limit' => 1], $stub);
$ok($status === 200 && count($ans['claims']) === 1 && $ans['truncated'] === true, 'the limit truncates and says so');
[$status, $ans] = memory_office_query($pdo, $ctx, ['scopes' => ['org'], 'query' => 'forklift'], static fn () => [null, 'down']);
$ok($status === 503 && $ans['error'] === 'memory_unavailable', 'MaluDB down: 503 memory_unavailable');
$pdo->exec('UPDATE estate_memory_settings SET rate_per_min = 5 WHERE id = 1');
$pdo->exec("DELETE FROM activity_log WHERE action = 'memory.query' AND entity_type = 'locations' AND entity_id = {$deskId}");
$last = null;
for ($i = 0; $i < 6; $i++) { [$last, $ans] = memory_office_query($pdo, $ctx, ['scopes' => ['org'], 'query' => 'x'], $stub); }
$ok($last === 429 && $ans['error'] === 'rate', 'the sixth query in a minute at a rate of 5: 429 rate');
$pdo->exec('UPDATE estate_memory_settings SET rate_per_min = 30 WHERE id = 1');

echo "== the office as a holder: a node's query with its envelope\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/memory.php?sub=query', $hrTok, ['scopes' => ['org'], 'query' => 'forklift']);
$ok($st === 401 && $e === 'bad_envelope', 'a node without an envelope: bad_envelope');
$env = $sign($envelope('agent:hr', $hrRef, ["dept:{$deptId}:read", 'org:read']), $hrRef, sodium_crypto_sign_secretkey($otherPair));
[$st, $j, $e] = $call('POST', '/api/v1/estate/memory.php?sub=query', $hrTok, ['scopes' => ['org'], 'query' => 'forklift', 'envelope' => $env]);
$ok($st === 401 && $e === 'bad_signature', 'signed with another key: bad_signature');
$env = $sign($envelope('agent:hr', $hrRef, ['org:read']), $hrRef, sodium_crypto_sign_secretkey($nodePair));
[$st, $j, $e] = $call('POST', '/api/v1/estate/memory.php?sub=query', $hrTok, ['scopes' => ["dept:{$deptId}"], 'query' => 'forklift', 'envelope' => $env]);
$ok($st === 403 && $e === 'forbidden', 'the authority covers org only; asking the department: forbidden');
$env = $sign($envelope('agent:hr', $hrRef, ['org:read'], 'internal'), $hrRef, sodium_crypto_sign_secretkey($nodePair));
[$st, $j, $e] = $call('POST', '/api/v1/estate/memory.php?sub=query', $hrTok, ['scopes' => ['org'], 'query' => 'forklift', 'classification' => 'restricted', 'envelope' => $env]);
$ok($st === 403 && $e === 'classification', 'asking restricted under an internal envelope: classification');
$env = $sign($envelope('agent:hr', $hrRef, ["dept:{$otherDept}:read", 'org:read']), $hrRef, sodium_crypto_sign_secretkey($nodePair));
[$st, $j, $e] = $call('POST', '/api/v1/estate/memory.php?sub=query', $hrTok, ['scopes' => ["dept:{$otherDept}", 'org'], 'query' => 'forklift', 'envelope' => $env]);
$ok(in_array($st, [200, 503], true) && ($st === 200 ? $j['holder'] === 'coordinator' : $e === 'memory_unavailable'), 'a server with a good envelope reads any department and org at the office (' . ($st === 200 ? 'answered' : '503 here, MaluDB down') . ')');
[$st, $j, $e] = $call('POST', '/api/v1/estate/memory.php?sub=query', $hrTok, ['scopes' => ['org'], 'query' => 'forklift', 'envelope' => $env]);
$ok($st === 409 && $e === 'replay', 'the same envelope again: replay');
$env = $sign($envelope('agent:hr', $hrRef, ['org:read'], 'internal', -200), $hrRef, sodium_crypto_sign_secretkey($nodePair));
[$st, $j, $e] = $call('POST', '/api/v1/estate/memory.php?sub=query', $hrTok, ['scopes' => ['org'], 'query' => 'forklift', 'envelope' => $env]);
$ok($st === 401 && $e === 'bad_envelope', 'an envelope that expires before it was issued: bad_envelope');
$env = $sign($envelope('agent:hr', $hrRef, ['org:read']), $deskRef, sodium_crypto_sign_secretkey($nodePair));
[$st, $j, $e] = $call('POST', '/api/v1/estate/memory.php?sub=query', $hrTok, ['scopes' => ['org'], 'query' => 'forklift', 'envelope' => $env]);
$ok($st === 401 && $e === 'bad_signature', 'an envelope signed by another node than the token\'s: bad_signature');
$after = json_decode((string) $pdo->query("SELECT after FROM activity_log WHERE action = 'memory.query' AND entity_type = 'locations' AND entity_id = {$hrId} ORDER BY id DESC LIMIT 1")->fetchColumn(), true) ?: [];
$ok(str_starts_with((string) ($after['envelope_id'] ?? ''), 'env_') && ($after['task_id'] ?? null) === 't_smoke' && ($after['originator'] ?? null) === 'agent:hr', 'the office\'s activity row for a node\'s query names the envelope, the task and the originator');

echo "== a host with two memberships (slice 4b, decision 9): a desk on the HR server's machine is published as the server alone\n";
$cd = desk_code_mint($pdo, $admin, '', $admin, 'desk');
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['surface' => 1, 'code' => $cd['code'], 'name' => "SMOKE {$run} dual", 'hostname' => 'hr', 'machine_id' => str_repeat(substr(md5('hr' . $run), 0, 8), 4), 'overlay_public_key' => $wg()]);
$ok($st === 201 && ($j['desk']['id'] ?? 0) > 0, 'a desk enrolled from the HR server\'s machine (the same machine id)');
$dualId = (int) $j['desk']['id']; $dualTok = (string) $j['token']; $dualRef = "desk:{$dualId}";
[$st, $j, $e] = $call('POST', '/api/v1/desks/heartbeat.php', $dualTok, ['surface' => 1, 'presence' => 'online', 'memory' => $facts(["dept:{$deptId}", 'org'], ["dept:{$deptId}", 'org'])]);
$ok($st === 200, 'its heartbeat carries the same face\'s facts');
[$st, $j, $e] = $call('GET', '/api/v1/estate/memory.php', $hubTok);
$ok($st === 200 && !in_array($dualRef, array_column($j['holders'], 'node'), true) && in_array($hrRef, array_column($j['holders'], 'node'), true), 'the hub is not given the desk of that host: the HR server is its one holder');
[$st, $j, $e] = $call('GET', '/api/v1/desks/memory.php', $dualTok);
$ok($st === 200 && in_array($hrRef, array_column($j['holders'], 'node'), true), 'that desk is still told its holders (the HR server among them: the face filters its own identities)');
$ok(substr_count((string) $pdo->query("SELECT pg_get_functiondef('mcp_resolve_token(text)'::regprocedure)")->fetchColumn(), 'token_scope') >= 1, 'db/193: the MCP token resolver says the token\'s scope and location (a desk token names its desk)');

echo "== settings\n";
$set = present_memory_for_settings($pdo);
$mine = array_values(array_filter($set['holders'], static fn ($h) => str_starts_with($h['display_name'], "SMOKE {$run}")));
$pub = array_values(array_filter($mine, static fn ($h) => $h['published']));
$dual = array_values(array_filter($mine, static fn ($h) => $h['node'] === $dualRef))[0] ?? [];
$ok(count($mine) === 4 && count($pub) === 3 && $set['fanout_max'] === 8 && $set['rate_per_min'] === 30 && in_array('org', array_column($set['office'], 'scope'), true) && $set['counts']['queries_24h'] >= 1,
    'Settings → Desks: the three reporting members published (the dual desk not), the limits, the office\'s scopes, the queries counted');
$ok(($dual['published'] ?? null) === false && str_starts_with((string) ($dual['why'] ?? ''), 'the node ') && str_ends_with((string) $dual['why'], ' of the same host'), 'the dual desk\'s row says why: the node of the same host');
$hrSet = array_values(array_filter($mine, static fn ($h) => $h['node'] === $hrRef))[0] ?? [];
$ok(count($hrSet['scopes'] ?? []) === 3 && ($hrSet['scopes'][0]['shared'] ?? null) === true && $hrSet['shared'] === $sorted(["dept:{$deptId}", "dept:{$otherDept}", 'org']), 'a holder row for the operator: every scope held with whether it is shared');

echo "== a node leaves\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/leave.php', $hrTok);
$ok($st === 200 && (int) $pdo->query("SELECT count(*) FROM estate_memory WHERE location_id = {$hrId}")->fetchColumn() === 0, 'the HR server leaves: its facts are gone');
[$st, $j, $e] = $call('GET', '/api/v1/desks/memory.php', $deskTok);
$ok($st === 200 && !in_array($hrRef, array_column($j['holders'], 'node'), true), 'the desk is no longer given it');
[$st, $j, $e] = $call('POST', '/api/v1/desks/heartbeat.php', $lapTok, ['surface' => 1, 'presence' => 'online']);
$ok($st === 200 && $j['memory_changed'] === true && $j['memory_peers_changed'] === true, 'the laptop hears both flags after the retirement');

// cleanup
$call('POST', '/api/v1/desks/leave.php', $deskTok);
$call('POST', '/api/v1/desks/leave.php', $lapTok);
$call('POST', '/api/v1/estate/leave.php', $hubTok);
$pdo->exec("UPDATE locations SET status = 'retired' WHERE name LIKE 'SMOKE {$run} %' AND status = 'active'");
$releaseSmoke();
echo "\n" . ($fails === 0 ? 'PASS' : "FAIL ({$fails})") . "\n";
exit($fails === 0 ? 0 : 1);
