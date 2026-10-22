<?php
declare(strict_types=1);

/**
 * Settings → Desks → "Enrol a desk": mint a one-time enrolment code for the signed-in person (db/187). The
 * code is shown ONCE, in its own field of this answer (never in `did`, which is logged), like a new token.
 * Minting again replaces the live code. Screen-only on purpose: a code is a secret and never passes through
 * the assistant. Gate: login (anyone who may own a desk: an active, internal human).
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/settings/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/estate/desks.php';
require_login(); require_post(); verify_csrf();
$pdo = db(); $me = (int) current_member_id();
$m = find_member_by_id($pdo, $me);
if ($m === null || ($m['member_kind'] ?? 'human') !== 'human' || !empty($m['is_external'])) {
    emit_action_status(false, ['errors' => ['Only a person of the business can enrol a desk.']]);
    respond_invalid(['Only a person of the business can enrol a desk.']);
}
$name = mb_substr(request_string('name'), 0, 120);
$c = desk_code_mint($pdo, $me, $name, $me);
log_activity($pdo, 'desk.code.mint', 'desk_enrollment_code', $c['id'], ['after' => ['desk_name' => $name !== '' ? $name : null]]);
emit_action_status(true, ['did' => 'Enrolment code created']);
if (wants_json()) {
    respond_saved(['did' => 'Enrolment code created', 'code' => $c['code'], 'expires_at' => json_ts($c['expires_at']), 'enroll_url' => app_url('/')]);
}
echo settings_section_html($pdo, $me, 'desks', ['newCode' => $c['code']]);
