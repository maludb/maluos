<?php
declare(strict_types=1);

/**
 * Action `business_logo_update` — upload the company's logo, or go back to the shipped one
 * (db/134). Gate: super. A file, not a setting: no approval policy applies, and the business
 * settings row's other fields are untouched. Logs `business_logo.update` or
 * `business_logo.remove`.
 *
 * Born after the cut-over: no template, so it says its own refusal (respond_invalid()).
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/settings/logo.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
[$logo, $errors] = business_logo_from_request('logo');
$remove = request_bool('remove_logo');
if ($errors === [] && $logo === null && !$remove) {
    $errors[] = 'Choose an image to upload, or tick "Use the standard logo".';
}
if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);
}

$before = business_logo_record($pdo);
$beforeFacts = $before === null ? null
    : ['mime' => $before['logo_mime'], 'size_bytes' => (int) $before['logo_size_bytes'], 'sha256' => $before['logo_sha256']];

if ($logo !== null) {
    try {
        store_business_logo($pdo, $logo);
    } catch (RuntimeException $ex) {
        error_log('business logo store failed: ' . $ex->getMessage());
        emit_action_status(false, ['errors' => [$ex->getMessage()]]);
        respond_invalid([$ex->getMessage()]);
    }
    log_activity($pdo, 'business_logo.update', 'business_settings', 1, [
        'before' => $beforeFacts,
        'after' => ['mime' => $logo['mime'], 'size_bytes' => $logo['size'], 'sha256' => $logo['sha256']],
    ]);
    emit_action_status(true, ['did' => 'The logo was uploaded', 'refresh' => 'settingsChanged']);
} else {
    clear_business_logo($pdo);
    log_activity($pdo, 'business_logo.remove', 'business_settings', 1, ['before' => $beforeFacts, 'after' => null]);
    emit_action_status(true, ['did' => 'Back to the standard logo', 'refresh' => 'settingsChanged']);
}
header('HX-Push-Url: /settings/business');
