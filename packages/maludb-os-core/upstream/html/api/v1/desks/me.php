<?php
declare(strict_types=1);

/** GET /api/v1/desks/me — the desk, its owner and this office's endpoints (Bearer desk token); writes nothing. */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/desks.php';

api_require_get();
$ctx = desk_authenticate();
api_json(desk_answer(db(), $ctx['desk'], $ctx['member']));
