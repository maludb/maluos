<?php
declare(strict_types=1);

/**
 * POST /api/v1/estate/apps/prepare — an application server, before the host half of bin/app_install.php
 * (db/194; app/features/applications/remote_install.php). Bearer = its node token. Served on the applications'
 * door and the internal port only, never on a public name: the answer carries what every application's
 * config/.env carries (the kernel's signing keys, the MaluDB token, the mail settings).
 * Body: {"key": "<catalog key>"} (optional). 403 not_allowed for a key the node's join code did not name.
 */
require_once dirname(__DIR__, 5) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 5) . '/app/features/estate/nodes.php';
require_once dirname(__DIR__, 5) . '/app/features/applications/remote_install.php';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') { api_error('method_not_allowed', 'Only POST is supported.', 405); }
$auth = node_authenticate();
$body = desk_body();
$allowed = app_install_node_apps($auth['node']);
$key = strtolower(trim((string) ($body['key'] ?? '')));
if ($allowed === [] || ($key !== '' && !in_array($key, $allowed, true))) {
    api_error('not_allowed', 'This server did not join as an application server for that application: its join code names the applications it may install.', 403);
}
$host = (string) (env('APP_HOST') ?: env('OS_HOST') ?: '');
log_activity(db(), 'application.remote_prepare', 'location', (int) $auth['node']['id'], ['source' => 'node', 'after' => ['key' => $key !== '' ? $key : null]]);
api_json([
    'surface' => 1,
    'node' => ['id' => (int) $auth['node']['id'], 'name' => (string) $auth['node']['name']],
    'apps' => $allowed,
    'by' => (string) $auth['member']['email'],
    'domain' => $host !== '' ? preg_replace('/^[^.]+\./', '', $host) : '',
    'scheme' => app_install_scheme(),
    'env' => array_filter([
        'APP_HOST' => $host,
        'ACTION_TOKEN_KEY' => (string) env('ACTION_TOKEN_KEY', ''),
        'ACTIONS_RELAY_KEY' => (string) env('ACTIONS_RELAY_KEY', ''),
        'MALUDB_API_TOKEN' => (string) env('MALUDB_API_TOKEN', ''),
        'MALUMAIL_API_KEY' => (string) env('MALUMAIL_API_KEY', ''),
        'MAIL_FROM' => (string) env('MAIL_FROM', ''),
        'MAIL_FROM_NAME' => (string) env('MAIL_FROM_NAME', ''),
    ], static fn (string $v): bool => $v !== ''),
]);
