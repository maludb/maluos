<?php
declare(strict_types=1);

/** Business settings (screen `business-settings`). Gate: super. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';

require_super_admin();

$pdo = db();
log_screen_view($pdo, 'business-settings');
if (wants_json()) {
    require_once dirname(__DIR__, 3) . '/app/features/settings/present.php';
    require_once dirname(__DIR__, 3) . '/app/features/settings/hours.php';
    require_once dirname(__DIR__, 3) . '/app/features/settings/logo.php';
    respond_screen([
        'settings' => present_business_settings(business_settings($pdo)),
        'saved' => request_string('saved') === '1',
        'timezones' => DateTimeZone::listIdentifiers(),
        'business_hours' => present_business_hours(find_business_hours($pdo)),
        'logo' => present_business_logo($pdo),
    ]);
}
$pageHtml = view('settings/business.php', [
    'settings' => business_settings($pdo),
    'saved' => request_string('saved') === '1',
]);
render_screen('Business settings · ' . business_name($pdo), $pageHtml,
    ['activeNav' => 'nav-settings', 'screen' => 'business-settings']);
