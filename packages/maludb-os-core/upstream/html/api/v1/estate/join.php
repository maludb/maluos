<?php
declare(strict_types=1);

/**
 * POST /api/v1/estate/join — a MaluOS server or inference host joins the estate (db/188; maluos
 * docs/phase13-slice1-nodes.md). Auth is the one-time node code in the body; the answer carries the node token
 * once. 403 bad_code for an unknown, expired, used code, a desk code, or one minted for the other node kind
 * (never which), 409 name_taken, 400 invalid.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/nodes.php';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
    api_error('method_not_allowed', 'Only POST is supported.', 405);
}
$body = desk_body();
if (isset($body['surface']) && (int) $body['surface'] !== DESK_SURFACE) {
    api_error('invalid', 'This office speaks estate surface ' . DESK_SURFACE . '.', 400);
}
$kind = $body['kind'] ?? null;
if ($kind !== null && !in_array($kind, NODE_KINDS, true)) {
    api_error('invalid', 'kind is server or inference (a desk enrols at /api/v1/desks/enroll).', 400);
}
$pdo = db();
$pdo->beginTransaction();
$code = desk_code_take($pdo, (string) ($body['code'] ?? ''), NODE_KINDS);
$member = $code !== null ? find_member_by_id($pdo, (int) $code['member_id']) : null;
if ($code === null || ($kind !== null && $kind !== $code['kind']) || !estate_operator($member)) {
    $pdo->rollBack();
    error_log('estate join: code refused (unknown, expired, used, a desk code, another kind, or its operator is gone)');
    api_error('bad_code', 'The node code is unknown, expired, already used or minted for another kind.', 403);
}
// From here the request runs as the operator who minted the code: their activity rows, their RLS context.
$_SESSION['member_id'] = (int) $member['id'];
$_SESSION['member_role'] = $member['role'];
$GLOBALS['__api_token_authed'] = true;
db_apply_context($pdo);

$principal = is_string($body['principal'] ?? null) ? $body['principal'] : null;
try {
    $made = node_join($pdo, $code, $body, $principal);
} catch (PDOException $ex) {
    $pdo->rollBack();
    if ($ex->getCode() === '23505') {
        api_error('name_taken', 'A location with that name already exists; choose another node name.', 409);
    }
    error_log('estate join failed: ' . $ex->getMessage());
    api_error('server_error', 'The node could not join.', 500);
}
// db/189: the node's place on the overlay (its WireGuard key in the body); --hub makes it the hub.
$oerr = overlay_join($pdo, (int) $made['node']['id'], $body);
if ($oerr === 'hub_exists') {
    $pdo->rollBack();
    api_error('hub_exists', 'The estate already has a hub; it must leave before another joins as the hub.', 409);
} elseif ($oerr !== null) {
    $pdo->rollBack();
    api_error('invalid', 'overlay_hub.endpoint is host:port.', 400);
}
$infKey = inference_key_mint($pdo, (int) $made['node']['id']);      // db/191: the estate's inference credential, shown once
inference_mark_seen($pdo, (int) $made['node']['id']);
$node = node_row($pdo, (int) $made['node']['id']);
log_activity($pdo, 'node.join', 'location', (int) $node['id'], ['source' => 'node',
    'after' => ['name' => $node['name'], 'kind' => $node['kind'], 'hostname' => $node['hostname'], 'app_version' => $node['app_version'], 'principal' => $principal]]);
$pdo->commit();

api_json(node_answer($pdo, $node) + ['token' => $made['token'], 'inference_key' => $infKey,
    'enrolled_by' => ['member_id' => (int) $member['id'], 'email' => (string) $member['email'], 'display_name' => (string) $member['display_name']]], 201);
