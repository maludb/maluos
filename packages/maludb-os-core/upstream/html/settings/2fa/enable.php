<?php
declare(strict_types=1);
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/settings/queries.php';
require_login(); require_post(); verify_csrf();
$pdo = db(); $me = current_member();
$secret = $_SESSION['totp_enroll_secret'] ?? '';
$code = preg_replace('/\D/', '', request_string('code'));

$reRender = function (string $err) use ($pdo, $me, $secret): never {
    emit_action_status(false, ['errors' => [$err]]);
    if (wants_json()) {
        // The React page still holds the QR it was given; it needs only the words.
        $secret === '' ? json_error('enrollment_expired', $err, 410) : respond_invalid([$err]);
    }
    $totp = totp_from_secret($secret);
    $totp->setLabel($me['email']); $totp->setIssuer((string) env('APP_NAME', 'MaluDb OS'));
    $qr = (new Endroid\QrCode\Writer\PngWriter())->write(new Endroid\QrCode\QrCode($totp->getProvisioningUri()))->getDataUri();
    echo settings_section_html($pdo, (int) $me['id'], 'security', ['enrolling' => true, 'qrDataUri' => $qr, 'manualKey' => $secret, 'error' => $err]);
    exit;
};

if ($secret === '') { $reRender('Enrollment expired — start again.'); }
$totp = totp_from_secret($secret);
$now = time(); $step = intdiv($now, TOTP_PERIOD); $ok = false;
foreach ([-1, 0, 1] as $off) { if (hash_equals($totp->at(($step + $off) * TOTP_PERIOD), $code)) { $ok = true; break; } }
if (!$ok) { $reRender('That code was not valid. Check your authenticator and try again.'); }

$codes = enable_totp($pdo, (int) $me['id'], $secret);
unset($_SESSION['totp_enroll_secret']);
log_activity($pdo, 'auth.2fa_enrolled', 'member', (int) $me['id']);
emit_action_status(true, ['did' => 'Two-factor authentication enabled']);
// The recovery codes are shown once, here or in the HTML below — their own field, never `did`.
if (wants_json()) {
    respond_saved(['did' => 'Two-factor authentication enabled', 'recovery_codes' => array_values($codes)]);
}
echo settings_section_html($pdo, (int) $me['id'], 'security', ['recoveryCodes' => $codes]);
