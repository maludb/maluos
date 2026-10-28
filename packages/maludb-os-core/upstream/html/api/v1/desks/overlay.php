<?php
declare(strict_types=1);

/** GET /api/v1/desks/overlay — the desk's view of the estate's network (Bearer desk token; db/189): the same answer as a node's. */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

api_require_get();
$ctx = desk_authenticate();
api_json(overlay_answer(db(), $ctx['desk']));
