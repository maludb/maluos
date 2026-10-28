<?php
declare(strict_types=1);

/** GET /api/v1/estate/keys — the public keys of every active member and the coordinator's (node or desk token; db/190). */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

api_require_get();
estate_authenticate_any();
api_json(estate_keys_answer(db()));
