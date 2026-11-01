<?php
declare(strict_types=1);

/**
 * GET /api/v1/desks/memory — the holders this desk may ask and the office's own scopes (Bearer desk token; db/192):
 * the same answer as /api/v1/estate/memory, named in the desk's endpoints as `memory` (null since Phase 12, real now).
 * POST …/memory/query (?sub=query): the office answers the desk's owner from its own memory as claims; no envelope,
 * the desk token is the desk's. ?all=1 (an operator's desk): every holder with `allowed` per scope.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

$ctx = desk_authenticate();
$pdo = db();
if (($_GET['sub'] ?? '') === 'query') {
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') { api_error('method_not_allowed', 'POST a query.', 405); }
    [$status, $answer] = memory_office_query($pdo, $ctx, desk_body());
    if ($status >= 400) { api_error((string) $answer['error'], (string) $answer['message'], $status); }
    api_json($answer);
}
api_require_get();
api_json(memory_holders_answer($pdo, $ctx['desk'], ($_GET['all'] ?? '') === '1' && estate_operator($ctx['member'])));
