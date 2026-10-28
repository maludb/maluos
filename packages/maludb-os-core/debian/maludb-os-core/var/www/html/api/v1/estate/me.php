<?php
declare(strict_types=1);

/** GET /api/v1/estate/me — the node, this office and its endpoints (Bearer node token; db/188); writes nothing. */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

api_require_get();
$ctx = node_authenticate();
api_json(node_answer(db(), $ctx['node']));
