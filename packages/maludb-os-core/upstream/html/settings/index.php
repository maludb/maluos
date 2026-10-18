<?php
declare(strict_types=1);

require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/settings/queries.php';

require_login();
$pdo = db();
$me = (int) current_member_id();

$section = request_string('section', 'profile');
if (!in_array($section, ['profile', 'notifications', 'security', 'tokens'], true)) {
    $section = 'profile';
}

$sectionHtml = settings_section_html($pdo, $me, $section);
if (($_SERVER['HTTP_HX_TARGET'] ?? '') === 'settings-content') {
    header('Vary: HX-Request');
    echo $sectionHtml;
    exit;
}
log_screen_view($pdo, 'settings');
if (wants_json()) {
    require_once dirname(__DIR__, 2) . '/app/features/settings/present.php';
    respond_screen(present_my_settings(find_member_by_id($pdo, $me), list_mcp_tokens($pdo, $me),
        app_url('/mcp/records'), app_url('/mcp/activity'))
        + ['section' => $section, 'timezones' => timezone_identifiers_list(),
           // db/142: the application app.<domain>/ opens after sign-in, and the ones they may choose.
           'default_application' => (static function () use ($pdo, $me): array {
               require_once dirname(__DIR__, 2) . '/app/features/applications/queries.php';
               return present_member_default_application($pdo, find_member_by_id($pdo, $me) ?? ['id' => $me]);
           })()]);
}
render_screen('Settings · MaluDb OS', view('settings/page.php', ['section' => $section, 'sectionHtml' => $sectionHtml]),
    ['activeNav' => 'nav-settings', 'screen' => 'settings']);
