<?php
declare(strict_types=1);
/**
 * Proof of K31 — GET /api/v1/apps/mine.php, the application switcher's feed (docs/build-specs/kernel-app-switcher.md).
 *
 *   php bin/test_app_switcher.php
 *
 * Makes a SMOKE application with its own token (never an installed application's — minting rotates the live one) and
 * asks the endpoint on the internal port: no token, a wrong token, no acting member, an agent, a person with no grant on
 * the caller, then the first super-admin — whose rows must equal what the launcher computes for them in this process,
 * with keys, launch paths, the current flag and a scoped application's scope paths. The SMOKE application is retired and
 * its token revoked at the end.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/applications/queries.php';
require_once dirname(__DIR__) . '/app/features/applications/present.php';
$pdo = db();
$me = (int) $pdo->query("SELECT id FROM members WHERE business_role = 'super_admin' AND status = 'active' AND member_kind = 'human' ORDER BY id LIMIT 1")->fetchColumn();
$_SESSION['member_id'] = $me;
db_apply_context($pdo);
$fails = 0;
$ok = static function (bool $c, string $label) use (&$fails): void { if (!$c) { $fails++; } echo ($c ? '  ok   ' : '  FAIL ') . $label . "\n"; };
$run = date('md-His');
$call = static function (string $token, ?int $acting, string $method = 'GET'): array {
    $ch = curl_init('http://127.0.0.1:8080/api/v1/apps/mine.php');
    $h = ['Accept: application/json'];
    if ($token !== '') { $h[] = 'Authorization: Bearer ' . $token; }
    if ($acting !== null) { $h[] = 'X-Acting-Member: ' . $acting; }
    curl_setopt_array($ch, [CURLOPT_CUSTOMREQUEST => $method, CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 30, CURLOPT_HTTPHEADER => $h]);
    $raw = (string) curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $j = json_decode($raw, true) ?: [];
    return [$code, $j['data'] ?? $j, $j['error']['code'] ?? null];
};
// ---- fixtures: a SMOKE application (its .invalid host keeps it out of every launcher list) and its token ----
$pdo->prepare("INSERT INTO applications (name, app_key, category, description, is_self_hosted, url, criticality, status, scope_kind, sso_path, created_by)
               VALUES (:n, :k, 'other', 'K31 proof caller', true, 'http://smoke-switcher.invalid', 'low', 'active', 'none', '/sso', :b)")
    ->execute(['n' => "SMOKE {$run} Switcher", 'k' => 'smoke_sw_' . str_replace('-', '_', $run), 'b' => $me]);
$appId = (int) $pdo->lastInsertId();
$token = mint_application_token($pdo, $appId, $me, "SMOKE {$run} switcher token")['raw'];
$agent = (int) $pdo->query("SELECT id FROM members WHERE status = 'active' AND member_kind = 'agent' ORDER BY id LIMIT 1")->fetchColumn();
$stranger = (int) $pdo->query("SELECT m.id FROM members m WHERE m.status = 'active' AND m.member_kind = 'human' AND m.business_role = 'user'
    AND NOT EXISTS (SELECT 1 FROM application_access x WHERE x.member_id = m.id AND x.application_id = {$appId}) ORDER BY m.id LIMIT 1")->fetchColumn();

echo "== refusals\n";
[$c] = $call('', $me);                       $ok($c === 401, "no token: 401 ($c)");
[$c] = $call('osapp_wrong', $me);            $ok($c === 401, "a wrong token: 401 ($c)");
[$c, , $e] = $call($token, null);            $ok($c === 400 && $e === 'invalid', "no acting member: 400 invalid ($c $e)");
[$c, , $e] = $call($token, $agent);          $ok($c === 403, "an agent as the acting member: 403 ($c $e)");
if ($stranger > 0) { [$c, , $e] = $call($token, $stranger); $ok($c === 403, "a person with no grant on the caller: 403 ($c $e)"); }
[$c] = $call($token, $me, 'POST');           $ok($c === 405, "POST: 405 ($c)");

echo "== the super-admin's rows equal the launcher's\n";
[$c, $d] = $call($token, $me);
$ok($c === 200 && ($d['schema'] ?? '') === 'os.my-applications/1', "200, schema os.my-applications/1 ($c)");
$ok((int) ($d['member_id'] ?? 0) === $me && (int) ($d['application']['id'] ?? 0) === $appId, 'member_id and the calling application echoed');
$_SESSION['member_id'] = $me; db_apply_context($pdo);
$expected = array_map(static fn (array $a): int => (int) $a['application_id'], find_launchable_applications($pdo));
$got = array_map(static fn (array $r): int => (int) $r['id'], $d['applications'] ?? []);
$ok($expected === $got && $got !== [], 'the ids, in the launcher\'s order (' . count($got) . ' applications)');
$first = $d['applications'][0] ?? [];
$ok(isset($first['key'], $first['name'], $first['icon'], $first['launch_path']) && $first['launch_path'] === '/launch/' . $first['id'], 'each row carries key, name, icon and launch_path /launch/<id>');
$ok(!in_array(true, array_column($d['applications'] ?? [], 'current'), true), 'none is current (the caller is not in the list: its host is .invalid)');
$ok(!in_array($appId, $got, true), 'the SMOKE caller itself is not offered');
$ok(($d['os_url'] ?? null) === (os_host() !== '' ? 'https://' . os_host() : null), 'os_url for a super-admin: ' . json_encode($d['os_url'] ?? null));
$scoped = array_values(array_filter($d['applications'] ?? [], static fn (array $r): bool => $r['scopes'] !== []));
if ($scoped !== []) {
    $s = $scoped[0]['scopes'][0];
    $ok($s['launch_path'] === '/launch/' . $scoped[0]['id'] . '?scope=' . $s['id'], "a scoped application's scope carries ?scope= ({$scoped[0]['name']} · {$s['name']})");
} else {
    echo "  (no scoped application held: the ?scope= path not exercised)\n";
}
$helpdesk = array_values(array_filter($d['applications'] ?? [], static fn (array $r): bool => $r['key'] === 'helpdesk'));
$ok($helpdesk !== [] && $helpdesk[0]['icon'] === 'feather-life-buoy', 'the Help Desk is in the list with its icon');
$ok(!$pdo->query("SELECT count(*) FROM activity_log WHERE created_at > now() - interval '20 seconds' AND entity_type = 'application' AND entity_id = {$appId}")->fetchColumn(), 'a read logs nothing');

// ---- cleanup ----
$pdo->exec("UPDATE mcp_access_tokens SET revoked_at = now() WHERE application_id = {$appId} AND revoked_at IS NULL");
$pdo->exec("UPDATE applications SET status = 'retired' WHERE id = {$appId}");
echo $fails === 0 ? "all passed (SMOKE {$run} Switcher retired)\n" : "{$fails} FAILED\n";
exit($fails === 0 ? 0 : 1);
