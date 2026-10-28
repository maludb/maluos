<?php
declare(strict_types=1);

/**
 * GET /api/v1/desks/estate — the estate for a desk whose owner is an operator (Bearer desk token; db/188): the
 * same answer as /api/v1/estate/nodes. A desk's answers name it in endpoints.estate, or null when its owner may
 * not see the estate (403 forbidden here).
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

api_require_get();
$ctx = desk_authenticate();
if (!estate_operator($ctx['member'])) {
    api_error('forbidden', 'The estate is not published to this desk.', 403);
}
api_json(estate_nodes_answer(db(), api_path_id()) ?? api_error('not_found', 'No such node.', 404));
