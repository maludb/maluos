<?php
declare(strict_types=1);

/**
 * POST /api/v1/estate/apps/register — an application server hands the kernel what the second half of the install
 * needs (db/194; app/features/applications/remote_install.php). Bearer = its node token; the door and the internal
 * port only. Body:
 *   {"key": "hr", "files": {"maludb-os.json": "<base64>", "mcp/action_registry.json": "…", "skills/…/SKILL.md": "…"},
 *    "host": {"base_url": "http://10.0.0.21:8101", "address": "10.0.0.21", "env": {"APP_INTERNAL_PORT": "8101", …},
 *             "answering": {"records": 200, …}, "has_token": false},
 *    "hire_agents": true, "grant_standing_departments": true, "source": "<repository>"}
 * Answers {"job": "<id>"}; the kernel half runs in the background as the operator who enrolled the node.
 * 403 not_allowed, 400 invalid, 409 busy (a registration of that application is still running).
 */
require_once dirname(__DIR__, 5) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 5) . '/app/features/estate/nodes.php';
require_once dirname(__DIR__, 5) . '/app/features/applications/remote_install.php';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') { api_error('method_not_allowed', 'Only POST is supported.', 405); }
$auth = node_authenticate();
$nodeId = (int) $auth['node']['id'];
$body = desk_body();
$key = strtolower(trim((string) ($body['key'] ?? '')));
if (preg_match('/^[a-z][a-z0-9_]{1,31}$/', $key) !== 1 || !in_array($key, app_install_node_apps($auth['node']), true)) {
    api_error('not_allowed', 'This server did not join as an application server for that application.', 403);
}
$host = is_array($body['host'] ?? null) ? $body['host'] : [];
$base = (string) ($host['base_url'] ?? '');
$address = (string) ($host['address'] ?? '');
if (preg_match('#^http://[A-Za-z0-9.:\[\]-]{1,253}:[0-9]{2,5}$#', $base) !== 1 || preg_match('/^[A-Za-z0-9.:-]{1,253}$/', $address) !== 1) {
    api_error('invalid', 'host.base_url is http://<this server>:<port> and host.address is this server\'s address.', 400);
}
if (preg_match('#^http://(127\.|localhost|\[?::1)#', $base) === 1) {
    api_error('invalid', 'host.base_url is the address the kernel reaches this server at, not loopback.', 400);
}
foreach (glob(app_install_staging_root() . '/' . $nodeId . '-' . $key . '-*', GLOB_ONLYDIR) ?: [] as $d) {
    if (!is_file($d . '/exit') && is_file($d . '/log.txt') && filemtime($d . '/log.txt') > time() - 1800) {
        api_error('busy', 'A registration of this application from this server is still running: ' . basename($d), 409);
    }
}
[$dir, $err] = app_bundle_stage($nodeId, $key, is_array($body['files'] ?? null) ? $body['files'] : []);
if ($dir === null) { api_error('invalid', (string) $err, 400); }
$m = json_decode((string) file_get_contents($dir . '/maludb-os.json'), true);
if (!is_array($m) || strtolower((string) ($m['catalog_key'] ?? '')) !== $key) {
    api_error('invalid', 'The bundle\'s maludb-os.json is not that application\'s.', 400);
}
$report = ['base_url' => $base, 'address' => $address, 'has_token' => !empty($host['has_token']),
           'env' => array_filter(is_array($host['env'] ?? null) ? $host['env'] : [], static fn ($v, $k): bool => is_string($k) && preg_match('/^[A-Z][A-Z0-9_]*_PORT$/', $k) === 1 && preg_match('/^[0-9]{2,5}$/', (string) $v) === 1, ARRAY_FILTER_USE_BOTH),
           'answering' => array_map('intval', is_array($host['answering'] ?? null) ? $host['answering'] : [])];
file_put_contents($dir . '/host-report.json', json_encode($report, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
$pdo = db();
$pdo->prepare('UPDATE locations SET node_address = :a, node_role = :r WHERE id = :id')->execute(['a' => $address, 'r' => 'application-server', 'id' => $nodeId]);
log_activity($pdo, 'application.remote_register', 'location', $nodeId, ['source' => 'node', 'after' => ['key' => $key, 'base_url' => $base, 'job' => basename($dir)]]);
$host0 = (string) (env('APP_HOST') ?: env('OS_HOST') ?: '');
app_install_start($dir, [
    'host-report' => $dir . '/host-report.json', 'result' => $dir . '/result.json', 'node-id' => $nodeId,
    'by' => (string) $auth['member']['email'], 'scheme' => app_install_scheme(),
    'domain' => $host0 !== '' ? preg_replace('/^[^.]+\./', '', $host0) : '',
    'proxy-address' => (string) env('OS_PROXY_ADDRESS', ''),
    'hire-agents' => !empty($body['hire_agents']), 'grant-standing-departments' => !empty($body['grant_standing_departments']),
    'source-note' => mb_substr((string) ($body['source'] ?? ''), 0, 200),
]);
api_json(['job' => basename($dir)], 202);
