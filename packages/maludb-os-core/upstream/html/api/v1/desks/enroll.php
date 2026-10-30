<?php
declare(strict_types=1);

/**
 * POST /api/v1/desks/enroll — a MaluOS desktop joins the estate as a desk (docs/build-specs/desk-enrolment.md).
 * Auth is the one-time code in the body; the answer carries the desk token once. 403 bad_code for an unknown,
 * expired or used code (never which), 409 name_taken, 400 invalid.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/desks.php';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
    api_error('method_not_allowed', 'Only POST is supported.', 405);
}
$body = desk_body();
if (isset($body['surface']) && (int) $body['surface'] !== DESK_SURFACE) {
    api_error('invalid', 'This office speaks desk surface ' . DESK_SURFACE . '.', 400);
}
$pdo = db();
$pdo->beginTransaction();
$code = desk_code_take($pdo, (string) ($body['code'] ?? ''));
$member = $code !== null ? find_member_by_id($pdo, (int) $code['member_id']) : null;
if ($code === null || $member === null || $member['status'] !== 'active' || ($member['member_kind'] ?? 'human') !== 'human' || !empty($member['is_external'])) {
    $pdo->rollBack();
    error_log('desk enroll: code refused (unknown, expired, used, or its member cannot own a desk)');
    api_error('bad_code', 'The enrolment code is unknown, expired or already used.', 403);
}
// From here the request runs as the owner: their activity rows, their RLS context.
$_SESSION['member_id'] = (int) $member['id'];
$_SESSION['member_role'] = $member['role'];
$GLOBALS['__api_token_authed'] = true;
db_apply_context($pdo);

$principal = is_string($body['principal'] ?? null) ? $body['principal'] : null;
try {
    $made = desk_enroll($pdo, $code, $body, $principal);
} catch (PDOException $ex) {
    $pdo->rollBack();
    if ($ex->getCode() === '23505') {
        api_error('name_taken', 'A location with that name already exists; choose another desk name.', 409);
    }
    error_log('desk enroll failed: ' . $ex->getMessage());
    api_error('server_error', 'The desk could not be enrolled.', 500);
}
// db/189: the desk's place on the overlay (its WireGuard key in the body); a desk is always a spoke.
unset($body['overlay_hub']);
overlay_join($pdo, (int) $made['desk']['id'], $body);
// db/190: the desk's signing key, when it brought one (else POST /api/v1/desks/key later)
if (is_string($body['public_key'] ?? null) && ssh_ed25519_raw($body['public_key']) !== null) {
    $pdo->prepare('UPDATE locations SET public_key = :k WHERE id = :id')->execute(['k' => trim($body['public_key']), 'id' => (int) $made['desk']['id']]);
}
$infKey = inference_key_mint($pdo, (int) $made['desk']['id']);      // db/191: the desk's inference key, shown once
inference_mark_seen($pdo, (int) $made['desk']['id']);
$desk = desk_row($pdo, (int) $made['desk']['id']);
log_activity($pdo, 'desk.enroll', 'location', (int) $desk['id'], ['source' => 'desk',
    'after' => ['name' => $desk['name'], 'hostname' => $desk['hostname'], 'app_version' => $desk['app_version'], 'principal' => $principal]]);
$pdo->commit();

api_json(desk_answer($pdo, $desk, $member) + ['token' => $made['token'], 'inference_key' => $infKey], 201);
