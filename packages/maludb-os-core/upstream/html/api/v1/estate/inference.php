<?php
declare(strict_types=1);

/**
 * Shared inference (db/191). GET /api/v1/estate/inference (a node or desk token): the backends the caller may use.
 * GET …/inference/peers (a node or desk token): the members allowed to call this host, with their keys' hashes.
 * POST …/inference/key (a node or desk token): a new inference key for the caller, shown once (a member enrolled
 * before db/191, or a rotation). POST …/inference/place (Bearer = an INFERENCE KEY; the `scheduler` entitlement):
 * {class, model, sensitivity, deadline_s, origin} → the backend to use and a lease. Writes nothing to activity: the
 * reads run on every refresh, `place` on every call.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$sub = (string) ($_GET['sub'] ?? '');
$pdo = db();
if ($sub === 'place') {
    if ($method !== 'POST') { api_error('method_not_allowed', 'POST a placement request.', 405); }
    $caller = inference_key_authenticate($pdo);
    $body = json_decode((string) file_get_contents('php://input'), true);
    api_json(inference_place($pdo, $caller, is_array($body) ? $body : []));
}
$ctx = estate_authenticate_any();
$loc = $ctx['node'] ?? $ctx['desk'];
if ($sub === 'key') {
    if ($method !== 'POST') { api_error('method_not_allowed', 'POST for a new key.', 405); }
    $pdo->beginTransaction();
    $raw = inference_key_mint($pdo, (int) $loc['id']);
    $pdo->commit();
    api_json(['ok' => true, 'surface' => DESK_SURFACE, 'node' => $loc['kind'] . ':' . (int) $loc['id'], 'inference_key' => $raw]);
}
if ($method !== 'GET') {
    api_error('method_not_allowed', 'GET the backends or the peers; POST …/key or …/place.', 405);
}
if ($sub === 'peers') {
    api_json(inference_peers_answer($pdo, $loc));
}
if ($sub !== '') {
    api_error('not_found', 'No such inference endpoint.', 404);
}
api_json(inference_backends_answer($pdo, $loc, ($_GET['all'] ?? '') === '1' && isset($ctx['member']) && estate_operator($ctx['member'])));
