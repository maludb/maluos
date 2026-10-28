<?php
declare(strict_types=1);

/** Action `business_settings_update` — log `business_settings.update`. Gate: super. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$before = business_settings($pdo);

$fields = [
    'business_name' => request_string('business_name'),
    'legal_name' => request_string('legal_name') ?: null,
    'base_currency' => strtoupper(request_string('base_currency', 'USD')),
    'timezone' => request_string('timezone', 'UTC'),
    'fiscal_year_start_month' => request_integer('fiscal_year_start_month') ?? 1,
    'default_payment_terms_days' => request_integer('default_payment_terms_days') ?? 30,
    'deal_quiet_days' => request_integer('deal_quiet_days') ?? 14,
    'prompt_payload_retention_days' => request_integer('prompt_payload_retention_days'),
    // What an hour is worth when the project names no rate (Time, owner's decision 2026-09-19).
    // Blank = no default: such time stays billable and unpriced, and is never invoiced at zero.
    'default_hourly_rate' => trim(request_string('default_hourly_rate')) !== '' ? trim(request_string('default_hourly_rate')) : null,
];

$errors = [];
if ($fields['default_hourly_rate'] !== null
    && (!is_numeric($fields['default_hourly_rate']) || (float) $fields['default_hourly_rate'] < 0 || (float) $fields['default_hourly_rate'] > 100000)) {
    $errors[] = 'The default hourly rate must be a number, zero or more.';
}
if ($fields['business_name'] === '' || mb_strlen($fields['business_name']) > 200) {
    $errors[] = 'The business needs a name (up to 200 characters).';
}
if (strlen($fields['base_currency']) !== 3 || !ctype_alpha($fields['base_currency'])) {
    $errors[] = 'Base currency is a three-letter code, such as USD.';
}
if (!in_array($fields['timezone'], DateTimeZone::listIdentifiers(), true)) {
    $errors[] = 'That is not a timezone.';
}
if ($fields['fiscal_year_start_month'] < 1 || $fields['fiscal_year_start_month'] > 12) {
    $errors[] = 'The fiscal year starts in one of the twelve months.';
}
if ($fields['default_payment_terms_days'] < 0 || $fields['default_payment_terms_days'] > 365) {
    $errors[] = 'Payment terms are 0–365 days.';
}
if ($fields['deal_quiet_days'] < 1 || $fields['deal_quiet_days'] > 365) {
    $errors[] = 'Quiet days are 1–365.';
}
if ($fields['prompt_payload_retention_days'] !== null
    && ($fields['prompt_payload_retention_days'] < 1 || $fields['prompt_payload_retention_days'] > 3650)) {
    $errors[] = 'Retention is 1–3650 days, or blank.';
}

if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    echo view('settings/business.php', ['settings' => array_merge($before, $fields), 'errors' => $errors]);
    exit;
}

check_approval($pdo, 'business_settings_update', 'business_settings.update',
    'Update business settings', $fields, 'business_settings', 1);

$after = update_business_settings($pdo, $fields);
log_activity($pdo, 'business_settings.update', 'business_settings', 1,
    ['before' => $before, 'after' => $after]);
emit_action_status(true, ['did' => 'Business settings saved']);

header('HX-Retarget: #page-content');
header('HX-Reswap: innerHTML');
header('HX-Push-Url: /settings/business?saved=1');   // React reads ?saved= for the banner (click-around step 5)
echo view('settings/business.php', ['settings' => $after, 'saved' => true]);
