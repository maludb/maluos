<?php
declare(strict_types=1);
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/settings/queries.php';
require_login(); require_post(); verify_csrf();
$pdo = db(); $me = current_member();
if ($me['totp_enabled_at'] !== null) {
    if (wants_json()) { respond_saved(['enrolling' => false]); }
    echo settings_section_html($pdo, (int) $me['id'], 'security'); exit;
}

$totp = OTPHP\TOTP::generate();
$totp->setLabel($me['email']);
$totp->setIssuer((string) env('APP_NAME', 'MaluDb OS'));
$_SESSION['totp_enroll_secret'] = $totp->getSecret();

$writer = new Endroid\QrCode\Writer\PngWriter();
$qrDataUri = $writer->write(new Endroid\QrCode\QrCode($totp->getProvisioningUri()))->getDataUri();

// Nothing is enabled yet — the secret waits in the session until a code confirms it. The QR and
// the manual key travel in their own fields of the JSON answer, once (owner's decision 3).
if (wants_json()) {
    respond_saved(['enrolling' => true, 'qr_data_uri' => $qrDataUri, 'manual_key' => $totp->getSecret()]);
}
echo settings_section_html($pdo, (int) $me['id'], 'security', [
    'enrolling' => true, 'qrDataUri' => $qrDataUri, 'manualKey' => $totp->getSecret(),
]);
