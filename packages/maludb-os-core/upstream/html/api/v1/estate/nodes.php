<?php
declare(strict_types=1);

/**
 * GET /api/v1/estate/nodes — the estate as the caller may see it (db/188): every active node with its health and
 * summary, every active desk, the open alerts and those cleared in the last hour. GET /api/v1/estate/nodes/ID
 * (?id= too) answers one node with its full last report. Bearer: a node token, or a desk token whose owner is an
 * operator (403 forbidden otherwise). Writes nothing.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

api_require_get();
$raw = api_bearer_token();
if (str_starts_with($raw, 'desk_')) {
    $ctx = desk_authenticate();
    if (!estate_operator($ctx['member'])) {
        api_error('forbidden', 'The estate is not published to this desk.', 403);
    }
} else {
    node_authenticate();
}
$id = api_path_id();
$ans = estate_nodes_answer(db(), $id);
if ($ans === null) {
    api_error('not_found', 'No such node.', 404);
}
api_json($ans);
