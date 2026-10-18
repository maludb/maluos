<?php
declare(strict_types=1);

/**
 * Screen `launcher` — the person face's home (A2, 2026-09-22; docs/build-specs/kernel-hosts.md).
 * The applications this person may open: what mcp_my_applications shows them — a live access
 * grant of their own or their department's, or everything for a super-admin — minus the
 * platform's own row, which is offered to a super-admin as "the operating system" instead. The
 * kernel's built-in applications are not here: they are the operating system's screens.
 *
 * Born after the cut-over: JSON only, no template.
 */
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/applications/queries.php';
require_once dirname(__DIR__) . '/app/features/applications/present.php';

require_login();

$pdo = db();
log_screen_view($pdo, 'launcher');
$member = current_member();
respond_screen([
    'business' => ['name' => business_name($pdo)],
    'member' => ['display_name' => (string) ($member['display_name'] ?? ''), 'is_super_admin' => is_super_admin()],
    'os_url' => is_super_admin() && os_host() !== '' ? 'https://' . os_host() : null,
    // db/142: the card app.<domain>/ opens after sign-in, marked on the launcher.
    'default_application_id' => isset($member['default_application_id']) ? (int) $member['default_application_id'] : null,
    'applications' => (static function () use ($pdo): array {
        $scopes = find_my_application_scopes($pdo);
        return array_map(static fn (array $a): array => present_launcher_application($a, $scopes[(int) $a['application_id']] ?? []),
            find_launchable_applications($pdo));
    })(),
]);
