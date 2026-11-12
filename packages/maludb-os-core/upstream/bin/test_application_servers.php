<?php
declare(strict_types=1);
/**
 * Proof of application servers, the kernel half (db/194; MaluOS Phase 14 slice 3, maluos
 * docs/phase14-application-servers.md): a server code that names applications, the three calls an application
 * server makes (prepare, register, job) under its node token, and the kernel's half of bin/app_install.php run on
 * the bundle as the web user.
 *
 *   APP_HOST=app.smoke.test STORAGE_ROOT=/tmp/kstore php -S 127.0.0.1:8091 -t html &
 *   BOS_INTERNAL_URL=http://127.0.0.1:8091 php bin/test_application_servers.php
 *
 * The application is SMOKE (catalog key smoke_as_<run>): its row is retired, its token revoked, its registry file
 * removed and the two nodes retired at the end. The catalog row and the retired application stay, named SMOKE.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/estate/nodes.php';
require_once dirname(__DIR__) . '/app/features/applications/remote_install.php';
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
$KEY = 'smoke_as_' . date('mdHis');       // a retired application keeps its app_key: every run has its own
$A = '/api/v1/estate/apps/';

echo "== a server code that names applications\n";
$c = desk_code_mint($pdo, $admin, "SMOKE {$run} app-1", $admin, 'server', [strtoupper($KEY), 'bad key!', 'hr', 'hr']);
$ok($c['apps'] === [$KEY, 'hr'], 'the code keeps the catalog keys it was given, normalised, once each');
$cd = desk_code_mint($pdo, $admin, '', $admin, 'desk', ['hr']);
$ok($cd['apps'] === [], 'a desk code names no application');
[$s, $j] = $call('POST', '/api/v1/estate/join.php', null, ['code' => $c['code'], 'kind' => 'server', 'name' => "SMOKE {$run} app-1", 'facts' => ['hostname' => 'smoke-app-1']]);
$tok = (string) ($j['token'] ?? '');
$nodeId = (int) ($j['node']['id'] ?? 0);
$ok(in_array($s, [200, 201], true) && $tok !== '' && $nodeId > 0, "the application server joined (node {$nodeId})");
$ok(app_install_node_apps(node_row($pdo, $nodeId)) === [$KEY, 'hr'], 'the node keeps the code\'s applications as its allowance');
$c2 = desk_code_mint($pdo, $admin, "SMOKE {$run} plain", $admin, 'server');
[$s, $j2] = $call('POST', '/api/v1/estate/join.php', null, ['code' => $c2['code'], 'kind' => 'server', 'name' => "SMOKE {$run} plain", 'facts' => ['hostname' => 'smoke-plain']]);
$tok2 = (string) ($j2['token'] ?? '');
$node2 = (int) ($j2['node']['id'] ?? 0);

echo "== prepare\n";
[$s, $j, $e] = $call('POST', $A . 'prepare.php', null, []);
$ok($s === 401, 'no token: 401');
[$s, $j, $e] = $call('POST', $A . 'prepare.php', $tok2, []);
$ok($s === 403 && $e === 'not_allowed', 'a server whose code named no application: 403 not_allowed');
[$s, $j, $e] = $call('POST', $A . 'prepare.php', $tok, ['key' => 'projects']);
$ok($s === 403 && $e === 'not_allowed', 'an application the code did not name: 403 not_allowed');
[$s, $p] = $call('POST', $A . 'prepare.php', $tok, ['key' => $KEY]);
$ok($s === 200 && ($p['apps'] ?? null) === [$KEY, 'hr'] && ($p['node']['id'] ?? 0) === $nodeId, 'prepare answers the node and its allowance');
$ok(($p['env']['ACTION_TOKEN_KEY'] ?? '') === (string) env('ACTION_TOKEN_KEY') && ($p['env']['ACTIONS_RELAY_KEY'] ?? '') !== '', 'prepare carries what an application\'s config/.env carries (the keys)');
$ok(($p['by'] ?? '') !== '' && in_array($p['scheme'] ?? '', ['http', 'https'], true) && ($p['domain'] ?? '') !== '', "prepare names the operator, the scheme and the domain ({$p['scheme']}://…{$p['domain']})");

echo "== register: what is refused\n";
// a skill is imported into MaluDB: only where this kernel has one (the local test kernel has none)
$withSkills = (string) env('MALUDB_API_URL', '') !== '' && (string) env('MALUDB_API_TOKEN', '') !== '';
if (!$withSkills) { echo "  note this kernel has no MaluDB: the bundle's skill is staged and not imported\n"; }
$manifest = ['schema' => 'maludb-os.application/1', 'catalog_key' => $KEY, 'name' => "SMOKE appsrv {$run}", 'description' => 'SMOKE: bin/test_application_servers.php',
    'business_area' => 'Operations', 'category' => 'other', 'version' => '0.0.1', 'vhost' => ['label' => 'smoke-appsrv'], 'icon' => 'feather-box',
    'endpoints' => [['name' => 'Records MCP', 'kind' => 'mcp', 'path' => '/mcp/records', 'port_env' => 'MCP_RECORDS_PORT', 'auth_kind' => 'bearer', 'agent_reachable' => true, 'mcp_surface_version' => '1.0']],
    'actions' => ['registry' => 'mcp/action_registry.json'], 'skills' => $withSkills ? ['skills/smoke-basics'] : [], 'sso' => ['path' => '/sso', 'logout_path' => '/sso/logout'], 'agents' => []];
$files = ['maludb-os.json' => base64_encode(json_encode($manifest)),
    'mcp/action_registry.json' => base64_encode(json_encode(['actions' => [$KEY . '_ping' => ['built' => true, 'endpoint' => '/ping.php', 'method' => 'POST', 'params' => []]]])),
    'skills/smoke-basics/SKILL.md' => base64_encode("---\nname: smoke-basics\ndescription: SMOKE skill of the application server proof.\n---\n\n# Smoke basics\n\nNothing to know.\n")];
$hostOk = ['base_url' => 'http://192.0.2.21:9101', 'address' => '192.0.2.21', 'env' => ['APP_INTERNAL_PORT' => '8101', 'MCP_RECORDS_PORT' => '8102', 'DB_PASSWORD' => 'never'],
    'answering' => ['Records MCP' => 200], 'has_token' => false];
[$s, $j, $e] = $call('POST', $A . 'register.php', $tok2, ['key' => $KEY, 'files' => $files, 'host' => $hostOk]);
$ok($s === 403 && $e === 'not_allowed', 'a server without the allowance: 403');
[$s, $j, $e] = $call('POST', $A . 'register.php', $tok, ['key' => 'projects', 'files' => $files, 'host' => $hostOk]);
$ok($s === 403, 'another application: 403');
[$s, $j, $e] = $call('POST', $A . 'register.php', $tok, ['key' => $KEY, 'files' => $files, 'host' => ['base_url' => 'http://127.0.0.1:8101', 'address' => '192.0.2.21']]);
$ok($s === 400 && $e === 'invalid', 'a loopback base_url: 400');
[$s, $j, $e] = $call('POST', $A . 'register.php', $tok, ['key' => $KEY, 'files' => $files + ['../evil.php' => base64_encode('<?php')], 'host' => $hostOk]);
$ok($s === 400, 'a path that leaves the bundle: 400');
[$s, $j, $e] = $call('POST', $A . 'register.php', $tok, ['key' => $KEY, 'files' => $files + ['.env' => base64_encode('X=1')], 'host' => $hostOk]);
$ok($s === 400, 'a dot file: 400');
$other = $manifest; $other['catalog_key'] = 'hr';
[$s, $j, $e] = $call('POST', $A . 'register.php', $tok, ['key' => $KEY, 'files' => ['maludb-os.json' => base64_encode(json_encode($other))] + $files, 'host' => $hostOk]);
$ok($s === 400, 'a manifest of another application under this key: 400');
$ok((int) $pdo->query("SELECT count(*) FROM applications WHERE app_key = '{$KEY}' AND status <> 'retired'")->fetchColumn() === 0, 'nothing was registered by the refused calls');

echo "== register: the kernel's half runs on the bundle\n";
[$s, $j] = $call('POST', $A . 'register.php', $tok, ['key' => $KEY, 'files' => $files, 'host' => $hostOk, 'source' => 'SMOKE ' . $run]);
$job = (string) ($j['job'] ?? '');
$ok($s === 202 && $job !== '', "accepted as job {$job}");
[$s, $jb, $e] = $call('POST', $A . 'register.php', $tok, ['key' => $KEY, 'files' => $files, 'host' => $hostOk]);
$ok($s === 409 && $e === 'busy', 'a second registration while the first runs: 409 busy');
[$s, $jo] = $call('GET', $A . 'job.php?id=' . rawurlencode($job), $tok2);
$ok($s === 404, 'another server cannot read the job');
$state = [];
for ($i = 0; $i < 90; $i++) {
    [$s, $state] = $call('GET', $A . 'job.php?id=' . rawurlencode($job), $tok);
    if (($state['state'] ?? 'running') !== 'running') { break; }
    sleep(2);
}
$out = (string) ($state['output'] ?? '');
$ok(($state['state'] ?? '') === 'done', 'the kernel\'s half finished: ' . ($state['state'] ?? '?') . (($state['state'] ?? '') === 'done' ? '' : "\n" . $out));
$token = (string) ($state['result']['application_token'] ?? '');
$ok(str_starts_with($token, 'osapp_'), 'the application token came back in the job\'s result');
[$s, $again] = $call('GET', $A . 'job.php?id=' . rawurlencode($job), $tok);
$ok(!isset($again['result']), 'and only once');
$ok(!str_contains($out, $token) && !str_contains($out, (string) env('ACTION_TOKEN_KEY')), 'the output shows no token and no key');
$app = $pdo->query("SELECT * FROM applications WHERE app_key = '{$KEY}' AND status <> 'retired'")->fetch() ?: [];
$appId = (int) ($app['id'] ?? 0);
$ok($appId > 0 && $app['internal_base_url'] === 'http://192.0.2.21:9101' && (int) $app['location_id'] === $nodeId, 'the application is registered at its node, with the address the kernel posts to');
$ok(str_starts_with((string) ($app['url'] ?? ''), ($p['scheme'] ?? 'http') . '://smoke-appsrv.'), "its public url is {$app['url']}");
$ep = $pdo->query("SELECT url FROM application_endpoints WHERE application_id = {$appId}")->fetchAll(PDO::FETCH_COLUMN);
$ok(count($ep) === 1 && str_ends_with((string) $ep[0], '/mcp/records'), 'its endpoint is registered by the public name');
$reg = json_decode((string) @file_get_contents(APP_ROOT . "/mcp/registries/{$KEY}.json"), true) ?: [];
$ok(($reg['base_url'] ?? '') === 'http://192.0.2.21:9101' && isset($reg['registry']['actions'][$KEY . '_ping']), 'the action registry carries the application server\'s address, not loopback');
$n = node_row($pdo, $nodeId);
$ok(($n['node_role'] ?? '') === 'application-server' && ($n['node_address'] ?? '') === '192.0.2.21', 'the node is labelled an application server at its address');
$st = $pdo->prepare("SELECT count(*) FROM mcp_access_tokens WHERE token_hash = :h AND scope = 'application' AND revoked_at IS NULL");
$st->execute(['h' => hash('sha256', $token)]);
$ok((int) $st->fetchColumn() === 1, 'the token is a live application token');
$ok(preg_match('/DB_PASSWORD|never/', (string) @file_get_contents(app_install_staging_root() . "/{$job}/host-report.json")) !== 1, 'the host report kept the ports only');

echo "== again: a re-run reconciles\n";
[$s, $j] = $call('POST', $A . 'register.php', $tok, ['key' => $KEY, 'files' => $files, 'host' => ['has_token' => true] + $hostOk]);
$job2 = (string) ($j['job'] ?? '');
for ($i = 0; $i < 90; $i++) {
    [$s, $state2] = $call('GET', $A . 'job.php?id=' . rawurlencode($job2), $tok);
    if (($state2['state'] ?? 'running') !== 'running') { break; }
    sleep(2);
}
$ok(($state2['state'] ?? '') === 'done' && !isset($state2['result']['application_token']), 'the second run finished and minted no second token');
$ok((int) $pdo->query("SELECT count(*) FROM applications WHERE app_key = '{$KEY}' AND status <> 'retired'")->fetchColumn() === 1, 'still one application');

echo "== tidy\n";
if ($appId > 0) {
    $pdo->exec("UPDATE mcp_access_tokens SET revoked_at = now() WHERE scope = 'application' AND revoked_at IS NULL AND id IN (SELECT id FROM mcp_access_tokens WHERE token_hash = " . $pdo->quote(hash('sha256', $token)) . ")");
    $pdo->exec("UPDATE applications SET status = 'retired' WHERE id = {$appId}");   // its name carries the run: the next run's is free
}
@unlink(APP_ROOT . "/mcp/registries/{$KEY}.json");
foreach ([$nodeId, $node2] as $id) { if ($id > 0) { node_retire($pdo, $id); } }
echo "\n" . ($fails === 0 ? 'PASS' : "FAIL ({$fails})") . ": application servers, the kernel half\n";
exit($fails === 0 ? 0 : 1);
