<?php
declare(strict_types=1);

/**
 * POST /api/v1/estate/overlay/key — a member's new WireGuard public key (Bearer node or desk token; db/189):
 * `maluctl estate overlay rotate`. The hub's new key reaches every spoke on their next refresh (overlay_changed).
 * 400 invalid for a key that is not 32 bytes in base64.
 */
require_once dirname(__DIR__, 5) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 5) . '/app/features/estate/nodes.php';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
    api_error('method_not_allowed', 'Only POST is supported.', 405);
}
$raw = api_bearer_token();
$ctx = str_starts_with($raw, 'desk_') ? desk_authenticate() : node_authenticate();
$loc = $ctx['desk'] ?? $ctx['node'];
$body = desk_body();
$key = $body['overlay_public_key'] ?? null;
if (!overlay_valid_key(is_string($key) ? $key : null)) {
    api_error('invalid', 'overlay_public_key is a WireGuard public key (32 bytes, base64).', 400);
}
$pdo = db();
$pdo->beginTransaction();
if (($loc['overlay_address'] ?? null) === null) {
    overlay_allocate($pdo, (int) $loc['id'], $key, false);     // a member that joined without a key gets its address now
} else {
    overlay_rotate($pdo, (int) $loc['id'], $key);
}
$pdo->commit();
$loc = isset($ctx['desk']) ? desk_row($pdo, (int) $loc['id']) : node_row($pdo, (int) $loc['id']);
api_json(['ok' => true, 'surface' => DESK_SURFACE, 'overlay' => overlay_block($pdo, $loc)]);
