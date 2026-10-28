<?php
declare(strict_types=1);

/** POST /api/v1/desks/key {"public_key": "ssh-ed25519 …"} — register (or replace) the desk's signing key (db/190; Bearer desk token). */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') { api_error('method_not_allowed', 'Only POST is supported.', 405); }
$ctx = desk_authenticate();
$body = desk_body();
$key = is_string($body['public_key'] ?? null) ? trim($body['public_key']) : '';
if (ssh_ed25519_raw($key) === null) { api_error('invalid', 'public_key is an ssh-ed25519 line.', 400); }
$pdo = db();
$pdo->prepare('UPDATE locations SET public_key = :k WHERE id = :id')->execute(['k' => $key, 'id' => (int) $ctx['desk']['id']]);
log_activity($pdo, 'desk.key', 'location', (int) $ctx['desk']['id'], ['source' => 'desk', 'after' => ['public_key' => $key]]);
api_json(['ok' => true, 'surface' => DESK_SURFACE, 'node' => 'desk:' . (int) $ctx['desk']['id'], 'public_key' => $key]);
