<?php
declare(strict_types=1);
/**
 * GET /api/v1/apps/mine.php — the applications the acting person may open, for the application switcher in every
 * application's header (K31, 2026-10-09; docs/build-specs/kernel-app-switcher.md). Bearer = the calling application's
 * token (internal port); X-Acting-Member = the person. The answer is the launcher's own rows (find_launchable_applications
 * + present_launcher_application, as html/launcher.php), so the switcher and the launcher can never disagree, plus each
 * row's app_key and the launch PATH (`/launch/<id>`, `?scope=<id>` per scope of a scoped application) that the application
 * appends to its OS_LAUNCHER_URL — the launcher's scheme is the installer's, not the kernel's to guess. `os_url` for a
 * super-admin. A person with no live grant on the calling application, or an agent, is refused by
 * application_acting_member() (403). A read: nothing is logged. Schema os.my-applications/1.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/api/directory.php';
require_once dirname(__DIR__, 4) . '/app/features/applications/queries.php';
require_once dirname(__DIR__, 4) . '/app/features/applications/present.php';
api_require_get();
$application = directory_authenticate();
$pdo = db();
$member = application_acting_member($pdo);          // the database context is theirs from here
$scopes = find_my_application_scopes($pdo);
$rows = [];
foreach (find_launchable_applications($pdo) as $a) {
    $row = present_launcher_application($a, $scopes[(int) $a['application_id']] ?? []);
    $row['key'] = (string) $a['app_key'];
    $row['launch_path'] = '/launch/' . $row['id'];
    $row['current'] = $row['id'] === $application['id'];
    foreach ($row['scopes'] as $i => $s) {
        $row['scopes'][$i]['launch_path'] = '/launch/' . $row['id'] . '?scope=' . $s['id'];
    }
    $rows[] = $row;
}
api_json([
    'schema' => 'os.my-applications/1',
    'member_id' => (int) $member['id'],
    'application' => ['id' => $application['id'], 'key' => $application['app_key']],
    'launcher_url' => app_host() !== '' ? 'https://' . app_host() . '/' : null,     // best effort; the application's OS_LAUNCHER_URL is authoritative
    'os_url' => is_super_admin() && os_host() !== '' ? 'https://' . os_host() : null,
    'applications' => $rows,
]);
