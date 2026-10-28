<?php
declare(strict_types=1);
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/settings/queries.php';
require_login(); require_post(); verify_csrf();
$pdo = db(); $meId = (int) current_member_id();
$member = find_member_by_id($pdo, $meId);
if ($member['totp_enabled_at'] === null) {
    emit_action_status(true, ['did' => 'Two-factor authentication is already off']);
    echo settings_section_html($pdo, $meId, 'security'); exit;
}
$code = request_string('code');
$ok = verify_totp_code($pdo, $member, $code) || verify_recovery_code($pdo, $meId, $code);
if (!$ok) {
    emit_action_status(false, ['errors' => ['Enter a valid current code (or recovery code) to disable 2FA.']]);
    echo settings_section_html($pdo, $meId, 'security', ['error' => 'Enter a valid current code (or recovery code) to disable 2FA.']);
    exit;
}
disable_totp($pdo, $meId);
log_activity($pdo, 'auth.2fa_disabled', 'member', $meId);
emit_action_status(true, ['did' => 'Two-factor authentication disabled']);
echo settings_section_html($pdo, $meId, 'security');
