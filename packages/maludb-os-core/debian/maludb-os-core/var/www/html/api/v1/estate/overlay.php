<?php
declare(strict_types=1);

/**
 * GET /api/v1/estate/overlay — the node's view of the estate's network (Bearer node token; db/189): itself, the hub,
 * the peers to configure (the hub alone for a spoke; every member for the hub) and every member's name and
 * address. Polled every refresh_s by maluos-overlay.service, and at once after a heartbeat says overlay_changed.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

api_require_get();
$ctx = node_authenticate();
api_json(overlay_answer(db(), $ctx['node']));
