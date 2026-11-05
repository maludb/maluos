<?php
declare(strict_types=1);

/**
 * POST /api/v1/estate/overlay/hub — the hub endpoint as a setting of the running estate (Bearer node token; db/189;
 * maluos docs/phase13-estate-behind-a-proxy.md, decision 2): `maluctl estate overlay hub HOST:PORT | off`.
 * {"endpoint": "host:port"} makes this node the hub, or changes the endpoint when it is the hub already (the office
 * behind a forward at its proxy, a GPU server with a public port); {"endpoint": null} releases the role: the estate
 * has no hub until a member claims one, and every spoke's `overlay` is null meanwhile. 409 hub_exists while another
 * member holds the role (it releases it, or is retired), 409 no_key for a member that joined without an overlay key,
 * 409 not_hub for a release by a member that is not the hub, 400 invalid for a bad endpoint. A desk token is refused
 * (401): a desk is never the hub. Every change bumps the overlay version, so the members refresh (overlay_changed).
 */
require_once dirname(__DIR__, 5) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 5) . '/app/features/estate/nodes.php';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
    api_error('method_not_allowed', 'Only POST is supported.', 405);
}
$ctx = node_authenticate();
$loc = $ctx['node'];
$body = desk_body();
if (!array_key_exists('endpoint', $body)) {
    api_error('invalid', 'endpoint is host:port (the hub as the spokes dial it), or null to release the hub role.', 400);
}
$endpoint = $body['endpoint'];
$pdo = db();
$pdo->beginTransaction();
if ($endpoint === null) {
    if (!overlay_release_hub($pdo, (int) $loc['id'])) {
        $pdo->rollBack();
        api_error('not_hub', 'This node is not the hub; nothing to release.', 409);
    }
    $what = 'released';
} else {
    $err = overlay_claim_hub($pdo, (int) $loc['id'], is_string($endpoint) ? $endpoint : '');
    if ($err === 'invalid_endpoint') {
        $pdo->rollBack();
        api_error('invalid', 'endpoint is host:port, the hub as the spokes dial it.', 400);
    }
    if ($err === 'no_key') {
        $pdo->rollBack();
        api_error('no_key', 'This node joined without an overlay key (--no-overlay); it cannot be the hub.', 409);
    }
    if ($err === 'hub_exists') {
        $pdo->rollBack();
        api_error('hub_exists', 'Another member is the hub; it releases the role (maluctl estate overlay hub off) or is retired before this node can take it.', 409);
    }
    $what = 'claimed';
}
log_activity($pdo, 'node.overlay_hub', 'location', (int) $loc['id'], ['source' => 'node',
    'after' => ['hub' => $what, 'endpoint' => $endpoint, 'name' => (string) $loc['name']]]);
$pdo->commit();
$node = node_row($pdo, (int) $loc['id']);
$hub = overlay_hub($pdo);
api_json(['ok' => true, 'surface' => DESK_SURFACE,
    'hub' => $hub !== null ? ['endpoint' => $hub['endpoint'], 'address' => $hub['address'], 'name' => overlay_label($hub['name']) . OVERLAY_NAME_SUFFIX, 'id' => $hub['id']] : null,
    'overlay' => overlay_block($pdo, $node)]);
