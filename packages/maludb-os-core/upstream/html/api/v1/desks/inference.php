<?php
declare(strict_types=1);

/**
 * GET /api/v1/desks/inference — the backends this desk may use (Bearer desk token; db/191): the same answer as
 * /api/v1/estate/inference, named in the desk's endpoints. POST …/inference/key (?sub=key): a new inference key for
 * the desk, shown once.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

$ctx = desk_authenticate();
$pdo = db();
if (($_GET['sub'] ?? '') === 'key') {
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') { api_error('method_not_allowed', 'POST for a new key.', 405); }
    $pdo->beginTransaction();
    $raw = inference_key_mint($pdo, (int) $ctx['desk']['id']);
    $pdo->commit();
    api_json(['ok' => true, 'surface' => DESK_SURFACE, 'node' => 'desk:' . (int) $ctx['desk']['id'], 'inference_key' => $raw]);
}
api_require_get();
// ?all=1 (an operator's desk): every backend of the estate with `allowed`, for `maluctl office inference --all`
api_json(inference_backends_answer($pdo, $ctx['desk'], ($_GET['all'] ?? '') === '1' && estate_operator($ctx['member'])));
