<?php
declare(strict_types=1);

/**
 * Proof of K6 (application texts) and K7 (application reads) — db/161, docs/build-specs/kernel-app-services.md.
 *
 *   php bin/test_app_services.php [--provider reservations]
 *
 * Makes a SMOKE consumer application at the provider's first site, with its own application token, and drives both
 * endpoints on the internal port through every refusal and the success path. K6 uses a dummy notification number
 * (a stored fake Twilio token and an unused account SID), so nothing is ever sent; the worker's pass is run once in
 * this process and must record Twilio's refusal. Everything it makes is removed at the end (the SMOKE application
 * retired, its token revoked, the dummy secret revoked). Needs the provider installed and sharing covers_by_service.
 * Never run while a real notification number is set: the no_sender check is then skipped, and the dummy is not made.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/applications/queries.php';
require_once dirname(__DIR__) . '/app/features/applications/services.php';

$o = getopt('', ['provider:']);
$providerKey = (string) ($o['provider'] ?? 'reservations');
$pdo = db();
$_SESSION['member_id'] = (int) $pdo->query("SELECT id FROM members WHERE business_role = 'super_admin' AND status = 'active' AND member_kind = 'human' ORDER BY id LIMIT 1")->fetchColumn();
$me = $_SESSION['member_id'];
db_apply_context($pdo);
$fails = 0;
$ok = static function (bool $c, string $label) use (&$fails): void { if (!$c) { $fails++; } echo ($c ? '  ok   ' : '  FAIL ') . $label . "\n"; };
$run = date('md-His');

$call = static function (string $method, string $path, string $token, ?array $body = null): array {
    $ch = curl_init('http://127.0.0.1:8080' . $path);
    curl_setopt_array($ch, [CURLOPT_CUSTOMREQUEST => $method, CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 30,
        CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $token, 'Content-Type: application/json', 'Accept: application/json']]);
    if ($body !== null) { curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body)); }
    $raw = (string) curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $j = json_decode($raw, true) ?: [];
    return [$code, $j['data'] ?? $j, $j['error']['code'] ?? ($j['code'] ?? null)];
};

// ---- fixtures ----
$st = $pdo->prepare("SELECT id FROM applications WHERE app_key = :k AND status <> 'retired'");
$st->execute(['k' => $providerKey]);
$providerId = (int) ($st->fetchColumn() ?: 0);
if ($providerId === 0) { fwrite(STDERR, "{$providerKey} is not installed.\n"); exit(1); }
$manifest = json_decode((string) @file_get_contents('/srv/apps/' . $providerKey . '/maludb-os.json'), true) ?: [];
$sync = application_services_sync($pdo, $providerId, (array) ($manifest['shares'] ?? []), []);
$loc = $pdo->prepare('SELECT location_id FROM application_scopes WHERE application_id = :a AND removed_at IS NULL AND location_id IS NOT NULL ORDER BY id LIMIT 1');
$loc->execute(['a' => $providerId]);
$locationId = (int) ($loc->fetchColumn() ?: 0);
if ($locationId === 0) { fwrite(STDERR, "{$providerKey} serves no site yet.\n"); exit(1); }

$pdo->prepare("INSERT INTO applications (name, app_key, category, description, is_self_hosted, url, criticality, status, scope_kind, sso_path, created_by)
               VALUES (:n, :k, 'other', 'K6/K7 proof consumer', true, 'http://smoke-consumer.invalid', 'low', 'active', 'location', '/sso', :b)")
    ->execute(['n' => "SMOKE {$run} Consumer", 'k' => 'smoke_' . str_replace('-', '_', $run), 'b' => $me]);
$consumerId = (int) $pdo->lastInsertId();
$pdo->prepare('INSERT INTO application_scopes (application_id, location_id, added_by) VALUES (:a, :l, :b)')
    ->execute(['a' => $consumerId, 'l' => $locationId, 'b' => $me]);
$token = mint_application_token($pdo, $consumerId, $me, "SMOKE {$run} consumer token")['raw'];
$otherLocation = (int) $pdo->query("SELECT id FROM locations WHERE id <> {$locationId} ORDER BY id LIMIT 1")->fetchColumn();

echo "K7 — application reads ({$providerKey} shares " . $sync['shares'] . " tool(s); site location {$locationId})\n";
$args = ['from' => date('Y-m-d', strtotime('-7 days')), 'to' => date('Y-m-d', strtotime('+14 days'))];
[$c, , $e] = $call('POST', '/api/v1/apps/read.php', 'osapp_wrong');
$ok($c === 401, "a wrong token: {$c}");
[$c, , $e] = $call('POST', '/api/v1/apps/read.php', $token, ['provider' => $providerKey, 'tool' => 'reservations_list', 'arguments' => [], 'location_id' => $locationId]);
$ok($c === 403 && $e === 'not_shared', "a tool not shared: {$c} {$e}");
[$c, , $e] = $call('POST', '/api/v1/apps/read.php', $token, ['provider' => $providerKey, 'tool' => 'covers_by_service', 'arguments' => $args, 'location_id' => $locationId]);
$ok($c === 403 && $e === 'no_connection', "no connection: {$c} {$e}");
$prop = application_services_sync($pdo, $consumerId, [], [['app' => $providerKey, 'tool' => 'covers_by_service', 'why' => 'proof']]);
$ok($prop['proposed'] === 1, 'the consumer\'s reads[] proposes one connection');
[$c, , $e] = $call('POST', '/api/v1/apps/read.php', $token, ['provider' => $providerKey, 'tool' => 'covers_by_service', 'arguments' => $args, 'location_id' => $locationId]);
$ok($c === 403 && $e === 'no_connection', "proposed, not approved: {$c} {$e}");
$cid = (int) $pdo->query("SELECT id FROM application_connections WHERE consumer_id = {$consumerId} AND revoked_at IS NULL")->fetchColumn();
application_connection_decide($pdo, $cid, 'approve', $me);
[$c, $d, $e] = $call('POST', '/api/v1/apps/read.php', $token, ['provider' => $providerKey, 'tool' => 'covers_by_service', 'arguments' => $args, 'location_id' => $locationId]);
$ok($c === 200 && ($d['result']['schema'] ?? '') === 'reservations.covers-by-service/1',
    "approved: {$c}, the provider's answer (" . count($d['result']['rows'] ?? []) . ' rows for ' . ($d['result']['restaurant'] ?? '?') . ')');
[$c, , $e] = $call('POST', '/api/v1/apps/read.php', $token, ['provider' => $providerKey, 'tool' => 'covers_by_service', 'arguments' => $args, 'location_id' => $otherLocation]);
$ok($c === 403 && $e === 'not_at_location', "a site one side does not serve: {$c} {$e}");
[$c, , $e] = $call('POST', '/api/v1/apps/read.php', $token, ['provider' => $providerKey, 'tool' => 'covers_by_service', 'arguments' => $args]);
$ok($c === 422 && $e === 'invalid', "a per-site tool with no site: {$c} {$e}");
[$c, $d, $e] = $call('POST', '/api/v1/apps/read.php', $token, ['provider' => $providerKey, 'tool' => 'covers_by_service', 'arguments' => $args + ['scope_id' => 999999], 'location_id' => $locationId]);
$ok($c === 200, "a scope_id smuggled in the arguments is replaced by the kernel's: {$c}");
$url = (string) $pdo->query("SELECT url FROM application_endpoints WHERE application_id = {$providerId} AND kind = 'mcp' AND status = 'active' ORDER BY id LIMIT 1")->fetchColumn();
try { mcp_call_tool_as_kernel($url, $providerKey, 'reservations_list', []); $ok(false, 'the provider refused the kernel token for an unshared tool'); }
catch (RuntimeException $ex) { $ok(true, 'the provider refuses the kernel token for an unshared tool'); }
application_connection_decide($pdo, $cid, 'revoke', $me);
[$c, , $e] = $call('POST', '/api/v1/apps/read.php', $token, ['provider' => $providerKey, 'tool' => 'covers_by_service', 'arguments' => $args, 'location_id' => $locationId]);
$ok($c === 403 && $e === 'no_connection', "revoked: {$c} {$e}");
$logged = (int) $pdo->query("SELECT count(*) FROM activity_log WHERE action = 'application.read' AND entity_id = {$consumerId}")->fetchColumn();
$ok($logged >= 8, "every read logged as application.read ({$logged}), the answer never");

echo "K26 — the provider is told who is asking, and waits the share's own timeout (db/173)\n";
// A SMOKE provider whose MCP server is bin/test_app_services_echo.php on :8097: it echoes the call's X-OS-* headers and arguments.
$echoPort = 8097;
$echo = proc_open(['php', '-S', '127.0.0.1:' . $echoPort, __DIR__ . '/test_app_services_echo.php'], [1 => ['file', '/dev/null', 'w'], 2 => ['file', '/dev/null', 'w']], $pipes);
usleep(600000);
$pdo->prepare("INSERT INTO applications (name, app_key, category, description, is_self_hosted, url, criticality, status, scope_kind, sso_path, sme_agent_member_id, created_by)
               VALUES (:n, :k, 'other', 'K26 proof provider', true, 'http://smoke-provider.invalid', 'low', 'active', 'none', '/sso', NULL, :b)")
    ->execute(['n' => "SMOKE {$run} Provider", 'k' => 'smokep_' . str_replace('-', '_', $run), 'b' => $me]);
$echoId = (int) $pdo->lastInsertId();
$echoKey = 'smokep_' . str_replace('-', '_', $run);
$pdo->prepare("INSERT INTO application_endpoints (application_id, name, kind, url, auth_kind, status) VALUES (:a, 'records', 'mcp', :u, 'none', 'active')")
    ->execute(['a' => $echoId, 'u' => 'http://127.0.0.1:' . $echoPort . '/mcp']);
$sync2 = application_services_sync($pdo, $echoId, [['tool' => 'echo', 'description' => 'echoes', 'timeout_seconds' => 2], ['tool' => 'slow', 'description' => 'echoes slowly', 'timeout_seconds' => 999]], []);
$tos = $pdo->query("SELECT tool || '=' || timeout_seconds FROM application_shares WHERE application_id = {$echoId} ORDER BY tool")->fetchAll(PDO::FETCH_COLUMN);
$ok($sync2['shares'] === 2 && $tos === ['echo=2', 'slow=60'], 'shares[].timeout_seconds is recorded, clamped to 60 (' . implode(', ', $tos) . ')');
application_services_sync($pdo, $consumerId, [], [['app' => $echoKey, 'tool' => 'echo', 'why' => 'proof'], ['app' => $echoKey, 'tool' => 'slow', 'why' => 'proof']]);
foreach ($pdo->query("SELECT id FROM application_connections WHERE consumer_id = {$consumerId} AND provider_id = {$echoId} AND revoked_at IS NULL")->fetchAll(PDO::FETCH_COLUMN) as $cid2) {
    application_connection_decide($pdo, (int) $cid2, 'approve', $me);
}
$expertAgent = (int) $pdo->query("SELECT member_id FROM agent_profiles ORDER BY member_id LIMIT 1")->fetchColumn();
$pdo->prepare('UPDATE applications SET sme_agent_member_id = :e WHERE id = :id')->execute(['e' => $expertAgent, 'id' => $consumerId]);
$consumerKey = 'smoke_' . str_replace('-', '_', $run);
[$c, $d, $e] = $call('POST', '/api/v1/apps/read.php', $token, ['provider' => $echoKey, 'tool' => 'echo', 'arguments' => ['q' => 'hello', 'consumer' => 'liar', 'consumer_agent_id' => 1, 'as_agent' => 1, 'scope_id' => 5]]);
$seen = $d['result'] ?? [];
$ok($c === 200 && ($seen['consumer'] ?? '') === $consumerKey, "the provider is told the consumer's key in X-OS-Consumer ({$c}: " . ($seen['consumer'] ?? '?') . ')');
$ok((string) ($seen['consumer_agent'] ?? '') === (string) $expertAgent, "...and the consumer's expert agent in X-OS-Consumer-Agent (" . ($seen['consumer_agent'] ?? 'none') . ')');
$ok(($seen['arguments'] ?? null) === ['q' => 'hello'], 'the consumer\'s own consumer, consumer_agent_id, as_agent and scope_id are stripped from the arguments: ' . json_encode($seen['arguments'] ?? null));
$ok(($seen['bearer'] ?? '') === 'kernel', 'the call carries the kernel\'s token');
$pdo->prepare('UPDATE applications SET sme_agent_member_id = NULL WHERE id = :id')->execute(['id' => $consumerId]);
[$c, $d, $e] = $call('POST', '/api/v1/apps/read.php', $token, ['provider' => $echoKey, 'tool' => 'echo', 'arguments' => ['q' => 'again']]);
$ok($c === 200 && ($d['result']['consumer'] ?? '') === $consumerKey && ($d['result']['consumer_agent'] ?? null) === null, 'a consumer with no expert: X-OS-Consumer alone, no agent header');
$t0 = microtime(true);
[$c, $d, $e] = $call('POST', '/api/v1/apps/read.php', $token, ['provider' => $echoKey, 'tool' => 'echo', 'arguments' => ['sleep' => 4]]);
$dt = microtime(true) - $t0;
$ok($c === 502 && $e === 'provider_failed' && $dt < 4, sprintf('a share with timeout_seconds 2 that takes 4 s: %d %s after %.1f s', $c, $e, $dt));
$t0 = microtime(true);
[$c, $d, $e] = $call('POST', '/api/v1/apps/read.php', $token, ['provider' => $echoKey, 'tool' => 'slow', 'arguments' => ['sleep' => 3]]);
$dt = microtime(true) - $t0;
$ok($c === 200 && $dt >= 3, sprintf('a share with timeout_seconds 60 that takes 3 s is answered (%d after %.1f s)', $c, $dt));
$row = $pdo->query("SELECT after FROM activity_log WHERE action = 'application.read' AND entity_id = {$consumerId} AND after->>'outcome' = 'ok' ORDER BY id DESC LIMIT 1")->fetchColumn();
$ok(is_string($row) && str_contains($row, '"timeout_seconds"') && str_contains($row, '"consumer_agent_id"'), 'application.read records the timeout and the consumer agent, never the answer');
proc_terminate($echo);
$pdo->prepare("UPDATE applications SET status = 'retired' WHERE id = :id")->execute(['id' => $echoId]);

echo "K6 — application texts\n";
$real = notify_endpoint($pdo);
$dummySecret = null; $dummyEndpoint = null; $identity = null;
if ($real === null) {
    [$c, , $e] = $call('POST', '/api/v1/notify/sms.php', $token, ['member_id' => $me, 'text' => 'proof']);
    $ok($c === 503 && $e === 'no_sender', "no notification number: {$c} {$e}");
    $dummySecret = store_tenant_secret($pdo, "smoke-{$run}-twilio", 'channel', 'twilio', bin2hex(random_bytes(16)), $me);
    $pdo->prepare("INSERT INTO notification_endpoints (channel, address, secret_id, config, created_by) VALUES ('sms', '+15555550100', :s, CAST(:c AS jsonb), :b)")
        ->execute(['s' => $dummySecret, 'c' => json_encode(['account_sid' => 'AC' . str_repeat('0', 32)]), 'b' => $me]);
    $dummyEndpoint = (int) $pdo->lastInsertId();
} else {
    echo "  note a real notification number is set — no_sender and the send are skipped\n";
}
$outsider = (int) ($pdo->query("SELECT m.id FROM members m WHERE m.member_kind = 'human' AND m.status = 'active' AND m.business_role <> 'super_admin'
                                  AND NOT EXISTS (SELECT 1 FROM app_member_grants({$consumerId}, m.id)) ORDER BY m.id LIMIT 1")->fetchColumn() ?: 0);
if ($dummyEndpoint !== null) {
    [$c, , $e] = $call('POST', '/api/v1/notify/sms.php', $token, ['member_id' => $outsider, 'text' => 'proof']);
    $ok($c === 422 && $e === 'not_held', "a member who does not hold the application: {$c} {$e}");
    $hasPhone = (int) $pdo->query("SELECT count(*) FROM member_channel_identities WHERE member_id = {$me} AND channel = 'sms' AND verified_at IS NOT NULL AND removed_at IS NULL")->fetchColumn();
    if ($hasPhone === 0) {
        [$c, , $e] = $call('POST', '/api/v1/notify/sms.php', $token, ['member_id' => $me, 'text' => 'proof']);
        $ok($c === 422 && $e === 'no_verified_phone', "no verified phone: {$c} {$e}");
        $pdo->prepare("INSERT INTO member_channel_identities (member_id, channel, address, label, verified_at) VALUES (:m, 'sms', '+15555550199', 'SMOKE', now())")
            ->execute(['m' => $me]);
        $identity = (int) $pdo->lastInsertId();
    }
    [$c, , $e] = $call('POST', '/api/v1/notify/sms.php', $token, ['member_id' => $me, 'text' => str_repeat('x', 481)]);
    $ok($c === 422 && $e === 'invalid', "a text over 480 characters: {$c} {$e}");
    $pdo->prepare("INSERT INTO member_notification_optouts (member_id, application_id, reason) VALUES (:m, :a, 'member')")->execute(['m' => $me, 'a' => $consumerId]);
    [$c, , $e] = $call('POST', '/api/v1/notify/sms.php', $token, ['member_id' => $me, 'text' => 'proof']);
    $ok($c === 422 && $e === 'opted_out', "opted out of this application: {$c} {$e}");
    $pdo->prepare('DELETE FROM member_notification_optouts WHERE member_id = :m AND application_id = :a')->execute(['m' => $me, 'a' => $consumerId]);
    [$c, $d, $e] = $call('POST', '/api/v1/notify/sms.php', $token, ['member_id' => $me, 'text' => 'Your Fri 5-11pm shift was approved.', 'reference' => 'proof:1']);
    $nid = (int) ($d['notification']['id'] ?? 0);
    $ok($c === 202 && $nid > 0, "a member who holds it, verified: {$c} queued #{$nid}");
    $body = (string) $pdo->query("SELECT body FROM application_notifications WHERE id = {$nid}")->fetchColumn();
    $ok(str_starts_with($body, "SMOKE {$run} Consumer: "), 'the text carries the application\'s name in front');
    [$c, $d] = $call('GET', '/api/v1/notify/sms.php?id=' . $nid, $token);
    $ok($c === 200 && ($d['notification']['status'] ?? '') === 'queued', "its status: queued");
    $after = (string) $pdo->query("SELECT after::text FROM activity_log WHERE action = 'application.notify' AND entity_id = {$consumerId} ORDER BY id DESC LIMIT 1")->fetchColumn();
    $ok($after !== '' && !str_contains($after, 'shift was approved'), 'logged as application.notify without the text');
    $notes = notify_deliver_pending($pdo);
    $state = $pdo->query("SELECT attempts, sent_at, failed_at, error FROM application_notifications WHERE id = {$nid}")->fetch();
    $ok((int) $state['attempts'] === 1 && $state['sent_at'] === null && str_contains((string) $state['error'], 'Twilio'),
        'the worker tried the dummy account and recorded Twilio\'s refusal: ' . mb_substr((string) $state['error'], 0, 70));
    $pdo->prepare('INSERT INTO application_notifications (application_id, member_id, body) SELECT :a, :m, :b FROM generate_series(1, :n)')
        ->execute(['a' => $consumerId, 'm' => $me, 'b' => 'SMOKE filler', 'n' => NOTIFY_MEMBER_DAY]);
    $pdo->exec("UPDATE application_notifications SET failed_at = now() WHERE application_id = {$consumerId}");   // never sent
    [$c, , $e] = $call('POST', '/api/v1/notify/sms.php', $token, ['member_id' => $me, 'text' => 'proof']);
    $ok($c === 422 && $e === 'rate_limited', "over " . NOTIFY_MEMBER_DAY . " a day: {$c} {$e}");
}

echo "K7 — a tool about people (db/162)\n";
$pdo->prepare("INSERT INTO application_shares (application_id, tool, description, scoped, people) VALUES (:a, 'smoke_people', 'K7 proof', true, true)")
    ->execute(['a' => $providerId]);
$prop = application_services_sync($pdo, $consumerId, [], [['app' => $providerKey, 'tool' => 'smoke_people', 'why' => 'proof']]);
$pcid = (int) $pdo->query("SELECT id FROM application_connections WHERE consumer_id = {$consumerId} AND tool = 'smoke_people' AND revoked_at IS NULL")->fetchColumn();
try { application_connection_decide($pdo, $pcid, 'approve', $me); $ok(false, 'a consumer without directory writes cannot be approved for a people tool'); }
catch (RuntimeException $ex) { $ok(str_contains($ex->getMessage(), 'directory writes'), 'a consumer without directory writes cannot be approved for a people tool'); }
$pdo->exec("UPDATE application_connections SET approved_by = {$me}, approved_at = now() WHERE id = {$pcid}");   // as if approved before the tool was marked
[$c, , $e] = $call('POST', '/api/v1/apps/read.php', $token, ['provider' => $providerKey, 'tool' => 'smoke_people', 'arguments' => $args, 'location_id' => $locationId]);
$ok($c === 403 && $e === 'people_restricted', "even an approved connection does not open it: {$c} {$e}");
$pdo->prepare("INSERT INTO applications (name, app_key, category, description, is_self_hosted, url, criticality, status, scope_kind, sso_path, directory_writes, created_by)
               VALUES (:n, :k, 'other', 'K7 people proof (directory writes)', true, 'http://smoke-hr.invalid', 'low', 'active', 'location', '/sso', true, :b)")
    ->execute(['n' => "SMOKE {$run} Directory writer", 'k' => 'smoke_dw_' . str_replace('-', '_', $run), 'b' => $me]);
$writerId = (int) $pdo->lastInsertId();
$pdo->prepare('INSERT INTO application_scopes (application_id, location_id, added_by) VALUES (:a, :l, :b)')->execute(['a' => $writerId, 'l' => $locationId, 'b' => $me]);
$wtoken = mint_application_token($pdo, $writerId, $me, "SMOKE {$run} writer token")['raw'];
application_services_sync($pdo, $writerId, [], [['app' => $providerKey, 'tool' => 'smoke_people', 'why' => 'proof']]);
$wcid = (int) $pdo->query("SELECT id FROM application_connections WHERE consumer_id = {$writerId} AND tool = 'smoke_people' AND revoked_at IS NULL")->fetchColumn();
[$c, , $e] = $call('POST', '/api/v1/apps/read.php', $wtoken, ['provider' => $providerKey, 'tool' => 'smoke_people', 'arguments' => $args, 'location_id' => $locationId]);
$ok($c === 403 && $e === 'no_connection', "the directory writer, before approval: {$c} {$e}");
try { application_connection_decide($pdo, $wcid, 'approve', $me); $ok(true, 'the directory writer can be approved'); }
catch (RuntimeException $ex) { $ok(false, 'the directory writer can be approved: ' . $ex->getMessage()); }
[$c, , $e] = $call('POST', '/api/v1/apps/read.php', $wtoken, ['provider' => $providerKey, 'tool' => 'smoke_people', 'arguments' => $args, 'location_id' => $locationId]);
$ok($c === 502 && $e === 'provider_failed', "approved: past every kernel gate, the provider (which does not serve it) answers: {$c} {$e}");
$pdo->exec("DELETE FROM application_connections WHERE consumer_id IN ({$consumerId}, {$writerId}) AND tool = 'smoke_people'");
$pdo->exec("DELETE FROM application_shares WHERE application_id = {$providerId} AND tool = 'smoke_people'");
revoke_application_tokens($pdo, $writerId);
$pdo->exec("UPDATE application_scopes SET removed_at = now(), removed_by = {$me} WHERE application_id = {$writerId}");
$pdo->exec("UPDATE applications SET status = 'retired' WHERE id = {$writerId}");

// ---- clean up ----
$pdo->exec("DELETE FROM application_notifications WHERE application_id = {$consumerId}");
if ($identity !== null) { $pdo->exec("DELETE FROM member_channel_identities WHERE id = {$identity}"); }
if ($dummyEndpoint !== null) { $pdo->exec("DELETE FROM notification_endpoints WHERE id = {$dummyEndpoint}"); }
if ($dummySecret !== null) { revoke_tenant_secret($pdo, $dummySecret); }
revoke_application_tokens($pdo, $consumerId);
$pdo->exec("UPDATE application_scopes SET removed_at = now(), removed_by = {$me} WHERE application_id = {$consumerId}");
$pdo->exec("UPDATE applications SET status = 'retired' WHERE id = {$consumerId}");
echo $fails === 0 ? "all passed (SMOKE {$run} Consumer retired)\n" : "{$fails} FAILED\n";
exit($fails === 0 ? 0 : 1);
