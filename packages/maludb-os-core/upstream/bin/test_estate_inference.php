<?php
declare(strict_types=1);
/**
 * Proof of shared inference, the kernel half of Phase 13 slice 3 (db/191; maluos docs/phase13-slice3-inference.md):
 * the inference key minted at join and enrol, the facts a heartbeat carries and the version they bump, the backends
 * each member is published (never itself, never a desk to another desk), the peers a serving host is given with the
 * keys' hashes, the policy's precedence (node > dept > kind > org, backend-specific over any, deny over allow), the
 * flags on heartbeats, key rotation, placement with and without the entitlement, the settings presenter, and what a
 * leaving node takes with it.
 *
 *   BOS_INTERNAL_URL=http://127.0.0.1:8089 php bin/test_estate_inference.php
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
$mk = static fn (string $kind) => desk_code_mint($pdo, $admin, '', $admin, $kind)['code'];
$releaseSmoke = static function () use ($pdo): void {
    $pdo->exec("UPDATE locations SET overlay_address_freed_at = now() - interval '31 days' WHERE name LIKE 'SMOKE %' AND status = 'retired' AND overlay_address IS NOT NULL");
    $pdo->exec("DELETE FROM estate_inference_policy WHERE note LIKE 'SMOKE %'");
};
$releaseSmoke();
// an earlier run that stopped short leaves active members holding addresses (and the hub): retire them the proper way
foreach ($pdo->query("SELECT id, kind FROM locations WHERE name LIKE 'SMOKE %' AND status = 'active'")->fetchAll() as $left) {
    $left['kind'] === 'desk' ? desk_retire($pdo, (int) $left['id']) : node_retire($pdo, (int) $left['id']);
}
$releaseSmoke();
$facts = static fn (array $models, bool $share = true, array $waits = ['interactive' => 1.5, 'agent' => 4, 'batch' => 20], int $queued = 0, string $contribution = 'always', int $port = 11435) => [
    'models' => array_map(static fn ($m) => ['name' => $m, 'family' => 'mock', 'size' => 4000000000, 'loaded' => $m === $models[0], 'backend' => 'local'], $models),
    'lanes' => ['local' => ['kind' => 'local', 'capacity' => 1, 'running' => 0, 'queued' => $queued]], 'queue' => ['queued' => $queued, 'running' => 0],
    'expected_wait_s' => $waits, 'share' => $share, 'contribution' => $contribution, 'port' => $port, 'api_version' => 1];

echo "== three members join with their keys: the hub (a server), a GPU host (inference), a desk\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, ['surface' => 1, 'kind' => 'server', 'code' => $mk('server'), 'name' => "SMOKE {$run} hub", 'principal' => 'host:hub', 'hostname' => 'hub',
    'os_release' => 'MaluOS 26.04', 'app_version' => 'maluos-estate 0.4.0', 'cpu_cores' => 4, 'memory_mb' => 8000, 'storage_gb' => 100, 'machine_id' => str_repeat(substr(md5('hub' . $run), 0, 8), 4),
    'overlay_public_key' => $wg(), 'overlay_hub' => ['endpoint' => 'hub.example.test:51820']]);
$ok($st === 201 && ($j['node']['id'] ?? 0) > 0 && str_starts_with((string) ($j['inference_key'] ?? ''), 'inf_'), "the hub joined; the answer carries an inference key once ({$j['node']['id']})");
$hubId = (int) $j['node']['id']; $hubTok = (string) $j['token']; $hubKey = (string) $j['inference_key']; $hubRef = "server:{$hubId}";
$ok(($j['endpoints']['inference'] ?? '') === app_url('/api/v1/estate/inference') && ($j['endpoints']['inference_peers'] ?? '') === app_url('/api/v1/estate/inference/peers') && ($j['editions'] ?? null) === [], 'the join answer names inference and inference_peers; editions empty (Community)');
$ok((string) $pdo->query("SELECT inference_key_hash FROM locations WHERE id = {$hubId}")->fetchColumn() === hash('sha256', $hubKey), 'only the key\'s SHA-256 is on the row');
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, ['surface' => 1, 'kind' => 'inference', 'code' => $mk('inference'), 'name' => "SMOKE {$run} gpu", 'principal' => 'host:gpu', 'hostname' => 'gpu',
    'machine_id' => str_repeat(substr(md5('gpu' . $run), 0, 8), 4), 'overlay_public_key' => $wg()]);
$ok($st === 201 && ($j['overlay']['role'] ?? '') === 'spoke' && str_starts_with((string) ($j['inference_key'] ?? ''), 'inf_'), 'the GPU host joined as a spoke with its key');
$gpuId = (int) $j['node']['id']; $gpuTok = (string) $j['token']; $gpuKey = (string) $j['inference_key']; $gpuRef = "inference:{$gpuId}"; $gpuAddr = (string) $j['overlay']['address'];
$cd = desk_code_mint($pdo, $admin, '', $admin, 'desk');
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['surface' => 1, 'code' => $cd['code'], 'name' => "SMOKE {$run} desk", 'hostname' => 'desk', 'machine_id' => str_repeat(substr(md5('desk' . $run), 0, 8), 4), 'overlay_public_key' => $wg()]);
$ok($st === 201 && ($j['desk']['id'] ?? 0) > 0 && str_starts_with((string) ($j['inference_key'] ?? ''), 'inf_') && ($j['endpoints']['inference'] ?? '') === app_url('/api/v1/desks/inference'), 'the desk enrolled with a key; endpoints.inference is the desks endpoint');
$deskId = (int) $j['desk']['id']; $deskTok = (string) $j['token']; $deskKey = (string) $j['inference_key']; $deskRef = "desk:{$deskId}";
$cd = desk_code_mint($pdo, $admin, '', $admin, 'desk');
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['surface' => 1, 'code' => $cd['code'], 'name' => "SMOKE {$run} laptop", 'hostname' => 'laptop', 'machine_id' => str_repeat(substr(md5('lap' . $run), 0, 8), 4), 'overlay_public_key' => $wg()]);
$lapId = (int) $j['desk']['id']; $lapTok = (string) $j['token']; $lapRef = "desk:{$lapId}";
$ok($st === 201, 'a second desk (a laptop with a GPU) enrolled');

echo "== the facts ride the heartbeat and bump the version only when the published view changes\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $gpuTok, ['surface' => 1, 'presence' => 'online', 'inference' => $facts(['qwen3:8b', 'nomic-embed-text'])]);
$ok($st === 200 && ($j['inference_changed'] ?? null) === true && array_key_exists('peers_changed', $j), 'the GPU host\'s first facts: stored, inference_changed true, peers_changed answered');
$row = $pdo->query("SELECT * FROM estate_inference WHERE location_id = {$gpuId}")->fetch();
$ok($row !== false && $row['share'] && $row['port'] === 11435 && count(json_decode($row['models'], true)) === 2 && json_decode($row['expected_wait_s'], true)['agent'] == 4, 'estate_inference holds the models, the switch, the port, the waits');
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $gpuTok, ['surface' => 1, 'presence' => 'online', 'inference' => $facts(['qwen3:8b', 'nomic-embed-text'], true, ['interactive' => 9, 'agent' => 12, 'batch' => 30], 3)]);
$ok($st === 200 && $j['inference_changed'] === false && (int) json_decode((string) $pdo->query("SELECT queue FROM estate_inference WHERE location_id = {$gpuId}")->fetchColumn(), true)['queued'] === 3, 'the queue and the waits change without a bump; the live numbers are kept');
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $gpuTok, ['surface' => 1, 'presence' => 'online', 'inference' => $facts(['qwen3:8b', 'nomic-embed-text', 'llama3.1:8b'])]);
$ok($st === 200 && $j['inference_changed'] === true, 'a new model bumps the version: inference_changed true');
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $gpuTok, ['surface' => 1, 'presence' => 'online', 'inference' => ['models' => [['name' => str_repeat('x', 9000)]]]]);
$ok($st === 400 && $e === 'invalid', 'facts over 8 KB are refused invalid');
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $hubTok, ['surface' => 1, 'presence' => 'online', 'inference' => $facts(['llama3.1:8b'], true, ['interactive' => 0.5, 'agent' => 2, 'batch' => 5])]);
$ok($st === 200, 'the hub reports a model of its own (a server shares always)');
[$st, $j, $e] = $call('POST', '/api/v1/desks/heartbeat.php', $deskTok, ['surface' => 1, 'presence' => 'online']);
$ok($st === 200 && array_key_exists('inference_changed', $j) && array_key_exists('peers_changed', $j), 'a desk heartbeat answers the two flags');

echo "== what each member is published\n";
[$st, $j, $e] = $call('GET', '/api/v1/desks/inference.php', $deskTok);
$names = array_column($j['backends'] ?? [], 'node');
$ok($st === 200 && in_array($gpuRef, $names, true) && in_array($hubRef, $names, true) && !in_array($deskRef, $names, true) && ($j['editions'] ?? null) === [] && $j['place'] === null, 'the desk: the GPU host and the hub, never itself; editions empty, no place URL');
$gpuRow = null;
foreach ($j['backends'] as $b) { if ($b['node'] === $gpuRef) { $gpuRow = $b; } }
$ok($gpuRow !== null && $gpuRow['address'] === $gpuAddr && $gpuRow['port'] === 11435 && str_ends_with($gpuRow['name'], '-gpu') && count($gpuRow['models']) === 3 && $gpuRow['class_max'] === null && $gpuRow['classification_max'] === 'internal' && $gpuRow['priority'] === 0 && $gpuRow['contribution'] === 'always',
    'a backend row: the overlay address and port, the overlay label, the models, the default ceilings');
[$st, $j, $e] = $call('GET', '/api/v1/estate/inference.php', $gpuTok);
$names = array_column($j['backends'] ?? [], 'node');
$ok($st === 200 && in_array($hubRef, $names, true) && !in_array($gpuRef, $names, true), 'the GPU host sees the hub, never itself (a node token at the estate endpoint)');
[$st, $j, $e] = $call('GET', '/api/v1/estate/inference.php', $deskTok);
$ok($st === 200 && in_array($gpuRef, array_column($j['backends'], 'node'), true), 'the estate endpoint takes a desk token too');
[$st, $j, $e] = $call('GET', '/api/v1/estate/inference.php', null);
$ok($st === 401, 'the backends need a token');
[$st, $j, $e] = $call('GET', '/api/v1/desks/inference.php?all=1', $deskTok);
$ok($st === 200 && count($j['backends']) >= 2 && array_key_exists('allowed', $j['backends'][0]), 'an operator\'s desk with ?all=1: every published backend, each with allowed');
[$st, $j, $e] = $call('POST', '/api/v1/desks/heartbeat.php', $lapTok, ['surface' => 1, 'presence' => 'online', 'inference' => $facts(['gemma3:4b'], true, ['interactive' => 1, 'agent' => 1, 'batch' => 1], 0, 'idle')]);
$ok($st === 200, 'the laptop shares while idle (its desk heartbeat carries the facts)');
[$st, $j, $e] = $call('GET', '/api/v1/desks/inference.php', $deskTok);
$ok($st === 200 && !in_array($lapRef, array_column($j['backends'], 'node'), true), 'decision 4: the desk is not given the laptop (a desk\'s contribution is never used by other desks)');
[$st, $j, $e] = $call('GET', '/api/v1/estate/inference.php', $hubTok);
$lapRow = null;
foreach ($j['backends'] as $b) { if ($b['node'] === $lapRef) { $lapRow = $b; } }
$ok($lapRow !== null && $lapRow['contribution'] === 'idle', 'the hub (a server) is given the laptop, contribution idle');
$pdo->exec("UPDATE locations SET presence = 'offline' WHERE id = {$lapId}");
[$st, $j, $e] = $call('GET', '/api/v1/estate/inference.php', $hubTok);
$ok(!in_array($lapRef, array_column($j['backends'], 'node'), true), 'an offline member is not published');
$pdo->exec("UPDATE locations SET presence = 'online' WHERE id = {$lapId}");
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $hubTok, ['surface' => 1, 'presence' => 'online', 'inference' => $facts(['llama3.1:8b'], false)]);
[$st, $j, $e] = $call('GET', '/api/v1/desks/inference.php', $deskTok);
$ok(!in_array($hubRef, array_column($j['backends'], 'node'), true), 'share off: the hub leaves the desk\'s list');
$call('POST', '/api/v1/estate/heartbeat.php', $hubTok, ['surface' => 1, 'presence' => 'online', 'inference' => $facts(['llama3.1:8b'], true, ['interactive' => 0.5, 'agent' => 2, 'batch' => 5])]);

echo "== the peers a serving host is given\n";
[$st, $j, $e] = $call('GET', '/api/v1/estate/inference/peers.php', $gpuTok);
[$st, $j, $e] = $call('GET', '/api/v1/estate/inference.php?sub=peers', $gpuTok);
$byNode = [];
foreach ($j['peers'] ?? [] as $p) { $byNode[$p['node']] = $p; }
$ok($st === 200 && isset($byNode[$deskRef], $byNode[$hubRef], $byNode[$lapRef]) && !isset($byNode[$gpuRef]), 'the GPU host\'s peers: the desk, the laptop and the hub, never itself');
$ok(($byNode[$deskRef]['key_hash'] ?? '') === hash('sha256', $deskKey) && ($byNode[$hubRef]['key_hash'] ?? '') === hash('sha256', $hubKey) && $byNode[$deskRef]['classification_max'] === 'internal' && $byNode[$deskRef]['class_max'] === null,
    'each peer carries its key\'s SHA-256 and its ceilings');
[$st, $j, $e] = $call('GET', '/api/v1/estate/inference.php?sub=peers', $lapTok);
$ok($st === 200 && !in_array($deskRef, array_column($j['peers'], 'node'), true) && in_array($hubRef, array_column($j['peers'], 'node'), true), 'the laptop\'s peers (a desk token): the hub, never the other desk');

echo "== the policy: precedence, the flags, the ceilings\n";
$r1 = inference_rule_add($pdo, ['subject' => 'kind:desk', 'backend_location_id' => $gpuId, 'allow' => false, 'note' => "SMOKE {$run} no desks on the gpu"], $admin);
[$st, $j, $e] = $call('GET', '/api/v1/desks/inference.php', $deskTok);
$ok(!in_array($gpuRef, array_column($j['backends'], 'node'), true) && in_array($hubRef, array_column($j['backends'], 'node'), true), 'deny kind:desk on the GPU host: the desk loses it, keeps the hub');
[$st, $j, $e] = $call('GET', '/api/v1/estate/inference.php?sub=peers', $gpuTok);
$ok(!in_array($deskRef, array_column($j['peers'], 'node'), true), 'and the GPU host no longer lists the desk as a peer');
[$st, $j, $e] = $call('POST', '/api/v1/desks/heartbeat.php', $deskTok, ['surface' => 1, 'presence' => 'online']);
$ok($st === 200 && $j['inference_changed'] === false && $j['peers_changed'] === true, 'the rule bumped both versions: the desk\'s next heartbeat says peers_changed (its read of the backends a moment ago already marked those heard)');
[$st, $j, $e] = $call('POST', '/api/v1/desks/heartbeat.php', $deskTok, ['surface' => 1, 'presence' => 'online']);
$ok($st === 200 && $j['inference_changed'] === false && $j['peers_changed'] === false, 'heard once, the flags fall');
$r2 = inference_rule_add($pdo, ['subject' => "node:{$deskId}", 'backend_location_id' => $gpuId, 'allow' => true, 'max_class' => 'batch', 'max_classification' => 'restricted', 'priority' => 5, 'note' => "SMOKE {$run} this desk may"], $admin);
[$st, $j, $e] = $call('GET', '/api/v1/desks/inference.php', $deskTok);
$gpuRow = null;
foreach ($j['backends'] as $b) { if ($b['node'] === $gpuRef) { $gpuRow = $b; } }
$ok($gpuRow !== null && $gpuRow['class_max'] === 'batch' && $gpuRow['classification_max'] === 'restricted' && $gpuRow['priority'] === 5, 'a node rule beats the kind rule: the desk has the GPU host again, at the rule\'s ceilings and priority');
[$st, $j, $e] = $call('GET', '/api/v1/estate/inference.php?sub=peers', $gpuTok);
$byNode = [];
foreach ($j['peers'] as $p) { $byNode[$p['node']] = $p; }
$ok(isset($byNode[$deskRef]) && $byNode[$deskRef]['class_max'] === 'batch' && $byNode[$deskRef]['classification_max'] === 'restricted', 'the peer row carries the same ceilings');
$r3 = inference_rule_add($pdo, ['subject' => 'org', 'backend_location_id' => null, 'allow' => false, 'note' => "SMOKE {$run} nobody"], $admin);
[$st, $j, $e] = $call('GET', '/api/v1/estate/inference.php', $hubTok);
$ok($j['backends'] === [], 'deny org on any backend: the hub is given nothing');
[$st, $j, $e] = $call('GET', '/api/v1/desks/inference.php', $deskTok);
$ok(count($j['backends']) === 1 && $j['backends'][0]['node'] === $gpuRef, 'but the desk\'s node rule still admits it to the GPU host (more specific than org)');
$ok(inference_rule_delete($pdo, (int) $r3['id']) && inference_rule_delete($pdo, (int) $r1['id']) && inference_rule_delete($pdo, (int) $r2['id']), 'the rules removed');
[$st, $j, $e] = $call('GET', '/api/v1/estate/inference.php', $hubTok);
$ok(in_array($gpuRef, array_column($j['backends'], 'node'), true), 'the default is back: every member may use every shared backend');

echo "== placement\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/inference.php?sub=place', $deskKey, ['class' => 'interactive', 'model' => 'qwen3:8b']);
$ok($st === 200 && $j['backend'] === null && $j['reason'] === 'not_entitled', 'without the entitlement: backend null, not_entitled');
[$st, $j, $e] = $call('POST', '/api/v1/estate/inference.php?sub=place', 'inf_' . bin2hex(random_bytes(24)), ['class' => 'interactive']);
$ok($st === 401, 'an unknown inference key: 401');
[$st, $j, $e] = $call('POST', '/api/v1/estate/inference.php?sub=place', $deskTok, ['class' => 'interactive']);
$ok($st === 401, 'a desk token is not an inference key');
inference_set_scheduler($pdo, true);
[$st, $j, $e] = $call('GET', '/api/v1/desks/inference.php', $deskTok);
$ok($j['editions'] === ['scheduler'] && $j['place'] === app_url('/api/v1/estate/inference/place') && $j['lease_s'] === 30, 'with the entitlement the backends answer names the place URL, editions scheduler, the lease');
[$st, $j, $e] = $call('POST', '/api/v1/estate/inference.php?sub=place', $deskKey, ['class' => 'interactive', 'model' => 'qwen3:8b', 'sensitivity' => 'internal', 'origin' => 'mg-1']);
$ok($st === 200 && ($j['backend']['node'] ?? '') === $gpuRef && $j['reason'] === 'placed' && $j['lease_s'] === 30 && $j['expected_wait_s'] == 1.5, 'placed: the one host that serves qwen3:8b, with a 30 s lease');
[$st, $j, $e] = $call('POST', '/api/v1/estate/inference.php?sub=place', $deskKey, ['class' => 'interactive', 'model' => 'llama3.1:8b']);
$ok($st === 200 && ($j['backend']['node'] ?? '') === $hubRef && $j['considered'] === 2, 'llama3.1:8b is on both: the lower expected wait (the hub) wins');
$r4 = inference_rule_add($pdo, ['subject' => "node:{$deskId}", 'backend_location_id' => $gpuId, 'allow' => true, 'priority' => 9, 'note' => "SMOKE {$run} prefer the gpu"], $admin);
[$st, $j, $e] = $call('POST', '/api/v1/estate/inference.php?sub=place', $deskKey, ['class' => 'interactive', 'model' => 'llama3.1:8b']);
$ok(($j['backend']['node'] ?? '') === $gpuRef, 'a priority rule places there first, whatever the wait');
inference_rule_delete($pdo, (int) $r4['id']);
[$st, $j, $e] = $call('POST', '/api/v1/estate/inference.php?sub=place', $deskKey, ['class' => 'interactive', 'model' => 'nope:1b']);
$ok($j['backend'] === null && $j['reason'] === 'no_model', 'a model nobody serves: no_model');
[$st, $j, $e] = $call('POST', '/api/v1/estate/inference.php?sub=place', $deskKey, ['class' => 'interactive', 'model' => 'qwen3:8b', 'sensitivity' => 'restricted']);
$ok($j['backend'] === null && $j['reason'] === 'classification', 'restricted above the internal ceiling: classification');
[$st, $j, $e] = $call('POST', '/api/v1/estate/inference.php?sub=place', $deskKey, ['class' => 'batch', 'model' => 'qwen3:8b', 'deadline_s' => 10]);
$ok($j['backend'] === null && $j['reason'] === 'no_capacity', 'a batch wait of 20 s over a 10 s deadline: no_capacity');
[$st, $j, $e] = $call('POST', '/api/v1/estate/inference.php?sub=place', $gpuKey, ['class' => 'interactive', 'model' => 'qwen3:8b']);
$ok($j['backend'] === null && $j['reason'] === 'no_model', 'a host never places itself');

echo "== key rotation\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/inference.php?sub=key', $deskTok);
$ok($st === 200 && str_starts_with((string) ($j['inference_key'] ?? ''), 'inf_') && $j['inference_key'] !== $deskKey, 'POST …/inference/key: a new key, shown once');
$deskKey2 = (string) $j['inference_key'];
[$st, $j, $e] = $call('POST', '/api/v1/estate/inference.php?sub=place', $deskKey, ['class' => 'interactive', 'model' => 'qwen3:8b']);
$ok($st === 401, 'the old key is refused');
[$st, $j, $e] = $call('POST', '/api/v1/estate/inference.php?sub=place', $deskKey2, ['class' => 'interactive', 'model' => 'qwen3:8b']);
$ok($st === 200 && $j['reason'] === 'placed', 'the new one places');
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $gpuTok, ['surface' => 1, 'presence' => 'online']);
$ok($st === 200 && $j['peers_changed'] === true, 'the serving host hears peers_changed after the rotation');
[$st, $j, $e] = $call('POST', '/api/v1/desks/inference.php?sub=key', $lapTok);
$ok($st === 200 && str_starts_with((string) ($j['inference_key'] ?? ''), 'inf_'), 'the desks endpoint rotates too');

echo "== settings\n";
$set = present_inference_for_settings($pdo);
$mine = array_values(array_filter($set['backends'], static fn ($b) => str_starts_with($b['display_name'], "SMOKE {$run}")));
$ok(count($mine) === 3 && count(array_filter($mine, static fn ($b) => $b['published'])) === 3 && $set['scheduler'] === true && $set['members_with_keys'] >= 4, 'Settings → Desks: the three reporting members published, the entitlement on, the keys counted');
inference_set_scheduler($pdo, false);

echo "== a node leaves\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/leave.php', $gpuTok);
$ok($st === 200 && (int) $pdo->query("SELECT count(*) FROM estate_inference WHERE location_id = {$gpuId}")->fetchColumn() === 0 && $pdo->query("SELECT inference_key_hash FROM locations WHERE id = {$gpuId}")->fetchColumn() === null, 'the GPU host leaves: its facts and its key hash are gone');
[$st, $j, $e] = $call('GET', '/api/v1/desks/inference.php', $deskTok);
$ok($st === 200 && !in_array($gpuRef, array_column($j['backends'], 'node'), true), 'the desk is no longer given it');
[$st, $j, $e] = $call('GET', '/api/v1/estate/inference.php?sub=peers', $hubTok);
$ok($st === 200 && !in_array($gpuRef, array_column($j['peers'], 'node'), true), 'the hub no longer lists it as a peer');
[$st, $j, $e] = $call('POST', '/api/v1/estate/inference.php?sub=place', $gpuKey, ['class' => 'interactive']);
$ok($st === 401, 'its key is dead');

// cleanup
$call('POST', '/api/v1/desks/leave.php', $deskTok);
$call('POST', '/api/v1/desks/leave.php', $lapTok);
$call('POST', '/api/v1/estate/leave.php', $hubTok);
$pdo->exec("UPDATE locations SET status = 'retired' WHERE name LIKE 'SMOKE {$run} %' AND status = 'active'");
$releaseSmoke();
echo "\n" . ($fails === 0 ? 'PASS' : "FAIL ({$fails})") . "\n";
exit($fails === 0 ? 0 : 1);
