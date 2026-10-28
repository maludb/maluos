<?php
declare(strict_types=1);
/**
 * Proof of the overlay, the kernel half of Phase 13 slice 1b (db/189; maluos docs/phase13-slice1b-overlay.md): the
 * hub's join, the spokes' addresses, the desks' place, the peers and names each member is given, rotation,
 * overlay_changed on heartbeats, leaving and the address quarantine, a hub that leaves.
 *
 *   BOS_INTERNAL_URL=http://127.0.0.1:8089 php bin/test_estate_overlay.php
 *
 * Runs on a clean overlay (the hub must not be set when it starts; it leaves everything freed at the end).
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
$wg = static fn (string $seed) => rtrim(base64_encode(hash('sha256', $seed, true)), '=') . '=';
$join = static fn (string $code, string $host, string $kind, array $extra = []) => ['surface' => 1, 'kind' => $kind, 'code' => $code, 'name' => "SMOKE {$run} {$host}", 'principal' => "host:{$host}",
    'hostname' => $host, 'os_platform' => 'linux', 'os_release' => 'MaluOS 26.04.20261028', 'app_version' => 'maluos-estate 0.2.0', 'cpu_cores' => 4, 'memory_mb' => 8000, 'storage_gb' => 100,
    'machine_id' => str_repeat(substr(md5($host . $run), 0, 8), 4)] + $extra;
// Re-runnable: the addresses an earlier run freed into quarantine are released (SMOKE rows only).
$releaseSmoke = static fn () => $pdo->exec("UPDATE locations SET overlay_address_freed_at = now() - interval '31 days' WHERE name LIKE 'SMOKE %' AND status = 'retired' AND overlay_address_freed_at IS NOT NULL");
$releaseSmoke();
$settings = overlay_settings($pdo);
$ok(!empty($settings['enabled']) && (string) $settings['range'] === '100.100.0.0/16', 'the overlay is on, 100.100.0.0/16 by default');
if (overlay_hub($pdo) !== null) { echo "  FAIL a hub is already set (" . overlay_hub($pdo)['name'] . "); this proof needs a clean overlay\n"; exit(1); }
$v0 = (int) $settings['version'];
$mk = static fn (string $kind = 'server') => desk_code_mint($pdo, $admin, '', $admin, $kind)['code'];

echo "== keys and endpoints\n";
$ok(overlay_valid_key($wg('a')) && !overlay_valid_key('not-a-key') && !overlay_valid_key(substr($wg('a'), 0, 43)), 'a WireGuard key is 32 bytes in base64');
$ok(overlay_valid_endpoint('vpn.example.com:51820') && overlay_valid_endpoint('203.0.113.5:51820') && !overlay_valid_endpoint('vpn.example.com') && !overlay_valid_endpoint('http://x:1'), 'an endpoint is host:port');
$ok(overlay_label("Ed's Laptop (home)") === 'ed-s-laptop-home' && overlay_label('db-1') === 'db-1' && overlay_label('…') === 'node', 'labels: lower case, [a-z0-9-]');

echo "== a spoke before any hub\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, $join($mk(), 'early', 'server', ['overlay_public_key' => $wg('early')]));
$early = (int) ($j['node']['id'] ?? 0); $earlyTok = (string) ($j['token'] ?? '');
$ok($st === 201 && $j['overlay'] === null && $j['endpoints']['overlay'] === null, 'a node joining before the hub: overlay null, endpoints.overlay null');
$ok(node_row($pdo, $early)['overlay_address'] === '100.100.0.2', 'but its address is allocated and kept (100.100.0.2)');
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, $join($mk(), 'nokey', 'server'));
$nokey = (int) ($j['node']['id'] ?? 0); $nokeyTok = (string) ($j['token'] ?? '');
$ok($st === 201 && node_row($pdo, $nokey)['overlay_address'] === null && $j['overlay'] === null, 'a node joining without a key (--no-overlay, an older client) has no address');
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, $join($mk(), 'badkey', 'server', ['overlay_public_key' => 'nope']));
$badkey = (int) ($j['node']['id'] ?? 0);
$ok($st === 201 && node_row($pdo, $badkey)['overlay_address'] === null, 'an invalid key is ignored: joined, no address');
node_retire($pdo, $badkey);

echo "== the hub\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, $join($mk(), 'office-1', 'server', ['overlay_public_key' => $wg('hub'), 'overlay_hub' => ['endpoint' => 'nope']]));
$ok($st === 400 && $e === 'invalid', "a hub with a bad endpoint is 400 ({$st} {$e})");
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, $join($mk(), 'office-1', 'server', ['overlay_public_key' => $wg('hub'), 'overlay_hub' => ['endpoint' => 'vpn.example.com:51820']]));
$hub = (int) ($j['node']['id'] ?? 0); $hubTok = (string) ($j['token'] ?? '');
$o = $j['overlay'] ?? null;
$ok($st === 201 && $o !== null && $o['role'] === 'hub' && $o['address'] === '100.100.0.1' && $o['prefix'] === 16 && $o['listen_port'] === 51820 && $o['hub'] === null && $o['name'] === "smoke-{$run}-office-1.internal", 'the hub joins: role hub, 100.100.0.1/16, listen port 51820, its name');
$ok($j['endpoints']['overlay'] === app_url('/api/v1/estate/overlay'), 'endpoints.overlay published to the hub');
$h = overlay_hub($pdo);
$ok($h !== null && $h['id'] === $hub && $h['endpoint'] === 'vpn.example.com:51820' && $h['public_key'] === $wg('hub'), 'the kernel records the hub, its endpoint and key');
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, $join($mk(), 'office-2', 'server', ['overlay_public_key' => $wg('hub2'), 'overlay_hub' => ['endpoint' => 'vpn2.example.com:51820']]));
$ok($st === 409 && $e === 'hub_exists', "a second hub is 409 hub_exists ({$st} {$e})");
$ok((int) $pdo->query("SELECT count(*) FROM locations WHERE name = 'SMOKE {$run} office-2'")->fetchColumn() === 0, 'the refused join rolled back (no location made)');
[$st, $j, $e] = $call('GET', '/api/v1/estate/me.php', $earlyTok);
$ok($st === 200 && $j['overlay'] !== null && $j['overlay']['role'] === 'spoke' && $j['overlay']['hub']['endpoint'] === 'vpn.example.com:51820' && $j['overlay']['hub']['address'] === '100.100.0.1' && $j['overlay']['hub']['public_key'] === $wg('hub') && $j['endpoints']['overlay'] !== null, 'the early node now sees the hub in me');

echo "== spokes and desks\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, $join($mk('inference'), 'gpu-1', 'inference', ['overlay_public_key' => $wg('gpu')]));
$gpu = (int) ($j['node']['id'] ?? 0); $gpuTok = (string) ($j['token'] ?? '');
$ok($st === 201 && $j['overlay']['role'] === 'spoke' && $j['overlay']['address'] === '100.100.0.3' && $j['overlay']['name'] === "smoke-{$run}-gpu-1.internal", 'an inference node: a spoke at 100.100.0.3 with its name');
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $gpuTok, ['presence' => 'online']);
$ok($st === 200 && $j['overlay_changed'] === false, 'its first heartbeat right after the join: nothing changed (the join answer had it all)');
$cd = desk_code_mint($pdo, $admin, '', $admin);
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['surface' => 1, 'code' => $cd['code'], 'name' => "SMOKE {$run} Ed's Laptop", 'hostname' => 'ed-laptop', 'machine_id' => str_repeat('ab', 16),
    'overlay_public_key' => $wg('desk'), 'overlay_hub' => ['endpoint' => 'x:1']]);
$desk = (int) ($j['desk']['id'] ?? 0); $deskTok = (string) ($j['token'] ?? '');
$ok($st === 201 && $j['overlay']['role'] === 'spoke' && $j['overlay']['address'] === '100.100.0.4' && $j['overlay']['name'] === "smoke-{$run}-ed-s-laptop.internal" && $j['endpoints']['overlay'] === app_url('/api/v1/desks/overlay'), 'a desk enrols with a key: a spoke at 100.100.0.4; overlay_hub ignored for a desk');
$cd2 = desk_code_mint($pdo, $admin, '', $admin);
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['surface' => 1, 'code' => $cd2['code'], 'name' => "SMOKE {$run} plain desk", 'hostname' => 'plain', 'machine_id' => str_repeat('cd', 16)]);
$plain = (int) ($j['desk']['id'] ?? 0); $plainTok = (string) ($j['token'] ?? '');
$ok($st === 201 && $j['overlay'] === null && $j['endpoints']['overlay'] === null, 'a desk without a key: no overlay');

echo "== what each member is given\n";
[$st, $j, $e] = $call('GET', '/api/v1/estate/overlay.php', $gpuTok);
$names = array_column($j['names'] ?? [], 'address', 'name');
$ok($st === 200 && $j['self']['address'] === '100.100.0.3' && $j['self']['role'] === 'spoke' && count($j['peers']) === 1 && $j['peers'][0]['address'] === '100.100.0.1' && $j['peers'][0]['public_key'] === $wg('hub') && $j['hub']['name'] === "smoke-{$run}-office-1.internal" && $j['refresh_s'] === 60, 'a spoke is given the hub as its one peer');
$ok(count($names) === 4 && $names["smoke-{$run}-office-1"] === '100.100.0.1' && $names["smoke-{$run}-early"] === '100.100.0.2' && $names["smoke-{$run}-gpu-1"] === '100.100.0.3' && $names["smoke-{$run}-ed-s-laptop"] === '100.100.0.4', 'and every member\'s name and address (the hub, two nodes, the desk; not the keyless ones)');
[$st, $j, $e] = $call('GET', '/api/v1/estate/overlay.php', $hubTok);
$peerAddrs = array_column($j['peers'] ?? [], 'address');
sort($peerAddrs);
$ok($st === 200 && $j['self']['role'] === 'hub' && $peerAddrs === ['100.100.0.2', '100.100.0.3', '100.100.0.4'] && in_array($wg('desk'), array_column($j['peers'], 'public_key'), true), 'the hub is given every spoke, the desk among them');
[$st, $j, $e] = $call('GET', '/api/v1/desks/overlay.php', $deskTok);
$ok($st === 200 && $j['self']['address'] === '100.100.0.4' && count($j['peers']) === 1 && $j['peers'][0]['address'] === '100.100.0.1', 'desks/overlay: the desk is given the hub');
[$st, $j, $e] = $call('GET', '/api/v1/estate/overlay.php', $nokeyTok);
$ok($st === 200 && $j['self'] === null && count($j['peers']) === 1, 'a keyless node sees the hub and no self');
$ok($call('GET', '/api/v1/estate/overlay.php', $deskTok)[0] === 401 && $call('GET', '/api/v1/desks/overlay.php', $gpuTok)[0] === 401, 'each path takes its own token kind');

echo "== overlay_changed and rotation\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $gpuTok, ['presence' => 'online']);
$ok($st === 200 && $j['overlay_changed'] === true, 'the desk that enrolled since: the node\'s next heartbeat says overlay_changed');
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $earlyTok, ['presence' => 'online']);
$ok($st === 200 && $j['overlay_changed'] === true && $call('POST', '/api/v1/estate/heartbeat.php', $earlyTok, ['presence' => 'online'])[1]['overlay_changed'] === false, 'the early node: changed once (the hub and the others came after it), then not');
[$st, $j, $e] = $call('POST', '/api/v1/estate/overlay/key.php', $hubTok, ['overlay_public_key' => $wg('hub-rotated')]);
$ok($st === 200 && $j['overlay']['role'] === 'hub' && overlay_hub($pdo)['public_key'] === $wg('hub-rotated'), 'the hub rotates its key');
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $gpuTok, ['presence' => 'online']);
$ok($j['overlay_changed'] === true && $call('POST', '/api/v1/estate/heartbeat.php', $gpuTok, ['presence' => 'online'])[1]['overlay_changed'] === false, 'a spoke\'s next heartbeat says overlay_changed once');
[$st, $j, $e] = $call('POST', '/api/v1/desks/heartbeat.php', $deskTok, ['presence' => 'online']);
$ok($j['overlay_changed'] === true && $call('GET', '/api/v1/desks/overlay.php', $deskTok)[1]['peers'][0]['public_key'] === $wg('hub-rotated'), 'the desk too, and its peer carries the new key');
$ok($call('POST', '/api/v1/estate/overlay/key.php', $gpuTok, ['overlay_public_key' => 'bad'])[0] === 400, 'a bad key on rotation is 400');
[$st, $j, $e] = $call('POST', '/api/v1/estate/overlay/key.php', $nokeyTok, ['overlay_public_key' => $wg('late')]);
$ok($st === 200 && $j['overlay']['address'] === '100.100.0.5', 'a keyless node that sends a key later gets its address (100.100.0.5)');
[$st, $j, $e] = $call('POST', '/api/v1/estate/overlay/key.php', $deskTok, ['overlay_public_key' => $wg('desk2')]);
$ok($st === 200 && desk_row($pdo, $desk)['overlay_public_key'] === $wg('desk2'), 'a desk rotates with its desk token');

echo "== settings\n";
$s = present_estate_for_settings($pdo);
$gpuRow = null; foreach ($s['nodes'] as $n) { if ($n['id'] === $gpu) { $gpuRow = $n; } }
$ok($s['overlay']['enabled'] && $s['overlay']['hub']['id'] === $hub && $s['overlay']['members'] === 5 && $gpuRow['overlay']['address'] === '100.100.0.3', 'Settings: the overlay, its hub, five members; the node row carries its address');
[$st, $j, $e] = $call('GET', '/api/v1/estate/nodes.php', $hubTok);
$deskRow = null; foreach ($j['nodes'] as $n) { if ($n['id'] === $desk) { $deskRow = $n; } }
$ok($deskRow !== null && $deskRow['overlay']['address'] === '100.100.0.4', 'the estate answer\'s desk row carries its address');

echo "== leaving, quarantine, the hub leaving\n";
$call('POST', '/api/v1/estate/leave.php', $earlyTok);
$r = node_row($pdo, $early);
$ok($r['overlay_address'] === '100.100.0.2' && $r['overlay_address_freed_at'] !== null, 'a node that leaves keeps its address row, freed into quarantine');
[$st, $j, $e] = $call('GET', '/api/v1/estate/overlay.php', $hubTok);
$ok(!in_array('100.100.0.2', array_column($j['peers'], 'address'), true) && !isset(array_column($j['names'], 'address', 'name')["smoke-{$run}-early"]), 'it is gone from the hub\'s peers and from the names');
$ok($call('POST', '/api/v1/estate/heartbeat.php', $gpuTok, ['presence' => 'online'])[1]['overlay_changed'] === true, 'the members hear of it');
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, $join($mk(), 'later', 'server', ['overlay_public_key' => $wg('later')]));
$later = (int) ($j['node']['id'] ?? 0); $laterTok = (string) ($j['token'] ?? '');
$ok($st === 201 && $j['overlay']['address'] === '100.100.0.6', 'a new member does not get the quarantined address (100.100.0.6)');
$pdo->exec("UPDATE locations SET overlay_address_freed_at = now() - interval '31 days' WHERE id = {$early}");
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, $join($mk(), 'reuse', 'server', ['overlay_public_key' => $wg('reuse')]));
$reuse = (int) ($j['node']['id'] ?? 0); $reuseTok = (string) ($j['token'] ?? '');
$ok($st === 201 && $j['overlay']['address'] === '100.100.0.2', 'after 30 days the address is reused (100.100.0.2)');
desk_retire($pdo, $plain);
$ok(desk_row($pdo, $plain)['overlay_address'] === null, '(a keyless desk retired: nothing to free)');
$call('POST', '/api/v1/estate/leave.php', $hubTok);
$ok(overlay_hub($pdo) === null && overlay_settings($pdo)['hub_location_id'] === null, 'the hub leaving unsets the hub');
[$st, $j, $e] = $call('GET', '/api/v1/estate/me.php', $gpuTok);
$ok($st === 200 && $j['overlay'] === null && $j['endpoints']['overlay'] === null && node_row($pdo, $gpu)['overlay_address'] === '100.100.0.3', 'the spokes see no overlay until a hub returns, their addresses kept');
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, $join($mk(), 'office-1b', 'server', ['overlay_public_key' => $wg('hub-b'), 'overlay_hub' => ['endpoint' => 'vpn.example.com:51820']]));
$hub2 = (int) ($j['node']['id'] ?? 0); $hub2Tok = (string) ($j['token'] ?? '');
$ok($st === 201 && $j['overlay']['role'] === 'hub' && $j['overlay']['address'] === '100.100.0.1', 'a new hub joins and takes 100.100.0.1 again');
[$st, $j, $e] = $call('GET', '/api/v1/estate/me.php', $gpuTok);
$ok($j['overlay']['hub']['public_key'] === $wg('hub-b'), 'the spokes see the new hub');
$ok((int) overlay_settings($pdo)['version'] > $v0 + 10, 'the version moved with every change');

// ---- cleanup: everything freed, the hub unset ----
foreach ([$gpuTok, $nokeyTok, $laterTok, $reuseTok, $hub2Tok] as $t) { $call('POST', '/api/v1/estate/leave.php', $t); }
desk_retire($pdo, $desk);
$releaseSmoke();
$ok(overlay_hub($pdo) === null && count(overlay_members($pdo)) === 0, 'cleanup: no hub, no live member, the SMOKE addresses released');
echo "\n" . ($fails === 0 ? 'PASS' : "FAIL ({$fails})") . "\n";
exit($fails === 0 ? 0 : 1);
