<?php
declare(strict_types=1);

/**
 * Federated memory (db/192). GET /api/v1/estate/memory (a node or desk token): the holders the caller may ask, scope by
 * scope, and the office's own scopes. GET …/memory/peers (a holder): the members allowed to ask this host, with their
 * scopes and ceilings (the signing keys stay at /api/v1/estate/keys). POST …/memory/query (a node token with an
 * envelope, or a desk token): the office answers from its own memory as claims. The reads write nothing to activity;
 * every answered query is one activity row (the scopes and the count, never the text).
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$sub = (string) ($_GET['sub'] ?? '');
$pdo = db();
$ctx = estate_authenticate_any();
$loc = $ctx['node'] ?? $ctx['desk'];
if ($sub === 'query') {
    if ($method !== 'POST') { api_error('method_not_allowed', 'POST a query.', 405); }
    $body = json_decode((string) file_get_contents('php://input'), true);
    [$status, $answer] = memory_office_query($pdo, $ctx, is_array($body) ? $body : []);
    if ($status >= 400) { api_error((string) $answer['error'], (string) $answer['message'], $status); }
    api_json($answer);
}
if ($method !== 'GET') {
    api_error('method_not_allowed', 'GET the holders or the peers; POST …/query.', 405);
}
if ($sub === 'peers') {
    api_json(memory_peers_answer($pdo, $loc));
}
if ($sub !== '') {
    api_error('not_found', 'No such memory endpoint.', 404);
}
api_json(memory_holders_answer($pdo, $loc, ($_GET['all'] ?? '') === '1' && isset($ctx['member']) && estate_operator($ctx['member'])));
