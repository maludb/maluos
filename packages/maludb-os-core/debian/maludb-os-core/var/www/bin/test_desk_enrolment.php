<?php
declare(strict_types=1);
/**
 * Proof of desk enrolment, the kernel half (db/187, docs/build-specs/desk-enrolment.md): the four endpoints
 * under /api/v1/desks/ on the internal port, the one-time code, the desk token's scope, presence and the sweep.
 *
 *   php bin/test_desk_enrolment.php
 *
 * Makes a SMOKE person (an ordinary user, no grants), mints them a code, and drives the endpoints the way
 * maluctl office does: a wrong code, the code, the code again, me, heartbeat with facts, offline, a re-enrolment
 * of the same machine, a taken name, the token on /api/v1/me (refused: one scope per surface), the sweep after
 * backdating, leave and the 410 that follows, a retirement from the estate's side. Everything it makes is
 * retired or revoked at the end; the SMOKE person is suspended.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/estate/desks.php';
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
$facts = static fn (string $host, string $mid) => ['surface' => 1, 'principal' => 'user:smoke', 'hostname' => $host, 'os_platform' => 'linux',
    'os_release' => 'MaluOS 26.04.20261022', 'variant' => 'Desktop', 'app_version' => 'maluos-desk 0.1.1', 'mcp_surface_version' => '1',
    'cpu_cores' => 8, 'memory_mb' => 15870, 'storage_gb' => 195, 'machine_id' => $mid];

// ---- fixtures: a SMOKE person, an ordinary user ----
$email = "smoke-desk-{$run}@example.invalid";
$pdo->prepare("INSERT INTO members (email, password_hash, display_name, role, business_role, email_verified_at, status) VALUES (:e, :h, :n, 'member', 'user', now(), 'active')")
    ->execute(['e' => $email, 'h' => hash_password(bin2hex(random_bytes(12)) . 'Aa1!'), 'n' => "SMOKE {$run} Desk Person"]);
$person = (int) $pdo->lastInsertId();
$mid = str_repeat(substr(md5($run), 0, 8), 4);

echo "== the code\n";
$c = desk_code_mint($pdo, $person, '', $admin);
$ok(preg_match('/^[A-Z2-9]{4}-[A-Z2-9]{4}$/', $c['code']) === 1, "mint_desk_code: eight unambiguous characters ({$c['code']})");
$c2 = desk_code_mint($pdo, $person, "SMOKE {$run} desk", $admin);
$ok(desk_code_take($pdo, $c['code']) === null, 'minting again expired the earlier code');
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['surface' => 1, 'code' => 'ZZZZ-ZZZZ'] + $facts('smoke-desk', $mid));
$ok($st === 403 && $e === 'bad_code', "a wrong code is 403 bad_code ({$st} {$e})");
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['surface' => 2, 'code' => $c2['code']]);
$ok($st === 400 && $e === 'invalid', "an unknown surface is 400 invalid ({$st} {$e})");
[$st, $j, $e] = $call('GET', '/api/v1/desks/enroll.php', null);
$ok($st === 405, "GET on enroll is 405 ({$st})");

echo "== enrol\n";
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['code' => strtolower($c2['code'])] + $facts('smoke-desk', $mid));
$ok($st === 201 && isset($j['token']) && str_starts_with($j['token'], 'desk_'), "enroll answers 201 with a desk token ({$st} {$e})");
$token = (string) ($j['token'] ?? '');
$deskId = (int) ($j['desk']['id'] ?? 0);
$ok($j['desk']['name'] === "SMOKE {$run} desk" && $j['desk']['status'] === 'active' && $j['desk']['presence'] === 'online', 'the desk carries the code\'s name, active and online');
$ok($j['owner']['member_id'] === $person && $j['owner']['email'] === $email, 'the owner is the code\'s person');
$ok($j['surface'] === 1 && $j['heartbeat_s'] === 300 && $j['endpoints']['records'] === app_url('/mcp/records') && $j['endpoints']['models'] === null && $j['endpoints']['memory'] === null, 'surface, heartbeat_s and the published endpoints (models, memory null)');
$row = desk_row($pdo, $deskId);
$ok($row['hostname'] === 'smoke-desk' && (int) $row['cpu_cores'] === 8 && (int) $row['memory_mb'] === 15870 && $row['operating_system'] === 'MaluOS 26.04.20261022' && $row['app_version'] === 'maluos-desk 0.1.1' && $row['machine_id'] === $mid && $row['external_ref'] === 'user:smoke' && $row['platform'] === 'desktop', 'the facts are on the location row');
$t = $pdo->query("SELECT scope, location_id, label, member_id FROM mcp_access_tokens WHERE token_hash = '" . hash('sha256', $token) . "'")->fetch();
$ok($t && $t['scope'] === 'desk' && (int) $t['location_id'] === $deskId && (int) $t['member_id'] === $person && (int) $row['enrollment_token_id'] > 0, 'the token is scope desk, bound to the desk, the owner\'s; the desk points at it');
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['code' => $c2['code']] + $facts('smoke-desk', $mid));
$ok($st === 403 && $e === 'bad_code', "the code cannot be used twice ({$st} {$e})");
$ok((int) $pdo->query("SELECT count(*) FROM activity_log WHERE action = 'desk.enroll' AND entity_id = {$deskId} AND actor_member_id = {$person} AND source = 'desk'")->fetchColumn() === 1, 'desk.enroll logged as the owner, source desk');
// mcp_resolve_token() is the read roles' alone (db/014); the same predicate, as app_rw: a live token of any scope resolves to its member.
$ok((int) $pdo->query("SELECT count(*) FROM mcp_access_tokens t JOIN members m ON m.id = t.member_id WHERE t.token_hash = '" . hash('sha256', $token) . "' AND t.revoked_at IS NULL AND (t.expires_at IS NULL OR t.expires_at > now()) AND m.status = 'active' AND m.id = {$person}")->fetchColumn() === 1, 'the MCP servers\' resolver predicate maps the desk token to the owner (records, activity)');

echo "== me, heartbeat, presence\n";
[$st, $j, $e] = $call('GET', '/api/v1/desks/me.php', $token);
$ok($st === 200 && $j['desk']['id'] === $deskId && $j['office']['url'] === app_url('/'), "me answers the desk ({$st})");
[$st, $j, $e] = $call('GET', '/api/v1/desks/me.php', 'desk_notatoken');
$ok($st === 401 && $e === 'unauthorized', "an unknown token is 401 ({$st} {$e})");
[$st, $j, $e] = $call('GET', '/api/v1/desks/me.php', null);
$ok($st === 401, "no token is 401 ({$st})");
[$st, $j, $e] = $call('GET', '/api/v1/me.php', $token);
$ok($st === 401, "a desk token is refused on /api/v1/me (one scope per surface) ({$st})");
$pdo->exec("UPDATE locations SET last_seen_at = now() - interval '1 hour', presence = 'offline' WHERE id = {$deskId}");
[$st, $j, $e] = $call('POST', '/api/v1/desks/heartbeat.php', $token, ['surface' => 1, 'presence' => 'online', 'app_version' => 'maluos-desk 0.1.2', 'facts' => ['hostname' => 'smoke-desk-2', 'cpu_cores' => 12, 'memory_mb' => 32000, 'storage_gb' => 500]]);
$row = desk_row($pdo, $deskId);
$ok($st === 200 && $j['desk']['presence'] === 'online' && $row['presence'] === 'online' && strtotime((string) $row['last_seen_at']) > time() - 60 && $row['hostname'] === 'smoke-desk-2' && (int) $row['cpu_cores'] === 12 && $row['app_version'] === 'maluos-desk 0.1.2', "heartbeat: online, last_seen_at now, facts updated ({$st})");
[$st, $j, $e] = $call('POST', '/api/v1/desks/heartbeat.php', $token, ['presence' => 'away']);
$ok($st === 400 && $e === 'invalid', "a presence that is not online|offline is 400 ({$st})");
[$st, $j, $e] = $call('POST', '/api/v1/desks/heartbeat.php', $token, ['presence' => 'offline']);
$ok($st === 200 && desk_row($pdo, $deskId)['presence'] === 'offline', 'offline heartbeat');
$ok((int) $pdo->query("SELECT count(*) FROM activity_log WHERE action LIKE 'desk.heartbeat%'")->fetchColumn() === 0, 'heartbeats are not in the activity log');
$pdo->exec("UPDATE locations SET presence = 'online', last_seen_at = now() - interval '20 minutes' WHERE id = {$deskId}");
$swept = desk_presence_sweep($pdo);
$ok(in_array($deskId, array_map('intval', array_column($swept, 'id')), true) && desk_row($pdo, $deskId)['presence'] === 'offline', 'the presence sweep marks a desk silent for three beats offline');
$pdo->exec("UPDATE locations SET presence = 'online', last_seen_at = now() - interval '5 minutes' WHERE id = {$deskId}");
$ok(!in_array($deskId, array_map('intval', array_column(desk_presence_sweep($pdo), 'id')), true), 'and leaves one heard from five minutes ago alone');

echo "== the same machine again, a taken name\n";
$c3 = desk_code_mint($pdo, $person, '', $admin);
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['code' => $c3['code'], 'name' => "SMOKE {$run} desk again"] + $facts('smoke-desk', $mid));
$ok($st === 201 && (int) $j['desk']['id'] !== $deskId, "re-enrolment of the same machine makes a new desk ({$st})");
$desk2 = (int) ($j['desk']['id'] ?? 0); $token2 = (string) ($j['token'] ?? '');
$ok(desk_row($pdo, $deskId)['status'] === 'retired' && $call('GET', '/api/v1/desks/me.php', $token)[0] === 410, 'the old desk is retired and its token answers 410');
$ok((int) $pdo->query("SELECT count(*) FROM mcp_access_tokens WHERE scope = 'desk' AND location_id = {$deskId} AND revoked_at IS NULL")->fetchColumn() === 0, 'the old token is revoked');
$c4 = desk_code_mint($pdo, $person, '', $admin);
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['code' => $c4['code'], 'name' => "SMOKE {$run} desk again"] + $facts('other-host', str_repeat('ab', 16)));
$ok($st === 409 && $e === 'name_taken', "a taken desk name is 409 name_taken ({$st} {$e})");
$ok(desk_code_take($pdo, $c4['code']) !== null, 'the code survives a refused enrolment');
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['code' => $c4['code']] + $facts('other-host', str_repeat('ab', 16)));
$ok($st === 201 && $j['desk']['name'] === "SMOKE {$run} Desk Person's desk", "a nameless enrolment is named after the owner ({$j['desk']['name']})");
$desk3 = (int) $j['desk']['id']; $token3 = (string) $j['token'];

echo "== settings\n";
$mine = find_my_desks($pdo, $person);
$ok(count($mine) === 2 && array_map('intval', array_column($mine, 'id')) === [$desk3, $desk2], 'find_my_desks lists the live desks, newest first');
require_once dirname(__DIR__) . '/app/features/settings/queries.php';
$ok(array_column(list_mcp_tokens($pdo, $person), 'id') === [], 'desk tokens do not show among the person\'s AI-access tokens');
$p = present_desk($mine[0]);
$ok($p['id'] === $desk3 && $p['presence'] === 'online' && !isset($p['token']) && $p['os'] === 'MaluOS 26.04.20261022', 'present_desk: no token, the facts');

echo "== leave and retire\n";
[$st, $j, $e] = $call('POST', '/api/v1/desks/leave.php', $token2);
$ok($st === 200 && $j['desk']['status'] === 'retired' && desk_row($pdo, $desk2)['status'] === 'retired', "leave retires the desk ({$st})");
$ok($call('GET', '/api/v1/desks/me.php', $token2)[0] === 410, 'after leave the token answers 410 retired (revoked, and the desk says why)');
$ok((int) $pdo->query("SELECT count(*) FROM mcp_access_tokens WHERE scope = 'desk' AND location_id = {$desk2} AND revoked_at IS NULL")->fetchColumn() === 0, 'the left desk\'s token is revoked for the MCP servers too');
$ok((int) $pdo->query("SELECT count(*) FROM activity_log WHERE action = 'desk.leave' AND entity_id = {$desk2} AND actor_member_id = {$person}")->fetchColumn() === 1, 'desk.leave logged as the owner');
desk_retire($pdo, $desk3);   // what locations/retire.php does for a desk, from the estate's side
$ok($call('POST', '/api/v1/desks/heartbeat.php', $token3, ['presence' => 'online'])[0] === 410, 'a desk retired from the estate: its heartbeat gets 410');
$pdo->exec("UPDATE mcp_access_tokens SET location_id = NULL WHERE scope = 'desk' AND location_id = {$desk3}");
$ok($call('GET', '/api/v1/desks/me.php', $token3)[0] === 401, 'a desk token without a desk is 401');

// ---- cleanup ----
$pdo->exec("UPDATE members SET status = 'suspended' WHERE id = {$person}");
echo "\n" . ($fails === 0 ? 'PASS' : "FAIL ({$fails})") . "\n";
exit($fails === 0 ? 0 : 1);
