<?php
declare(strict_types=1);

/**
 * Module stub screen (shell conversion, build plan 1.8).
 *
 * Every one of the 23 built-in modules is reachable from the navigation from day one. The ones
 * whose slice has not been built yet answer with this screen: what the module is (read from its
 * `applications` row — the registry is the source of truth, not a hand-copied list), which phase
 * builds it, and where its specification lives. It is a stub, and it says so; it never pretends
 * to hold data.
 */
function render_module_stub(string $moduleKey): never
{
    $module = module_by_key($moduleKey);
    if ($module === null) {
        http_response_code(404);
        exit('Unknown module.');
    }

    if ($module['module'] !== null) {
        require_module($module['module']);
    } else {
        require_login();
    }

    $pdo = db();
    $screen = $moduleKey . '-stub';
    log_screen_view($pdo, $screen);

    $st = $pdo->prepare(<<<'SQL'
        SELECT a.name, a.description, a.category, a.url, a.status,
               l.name AS location_name, d.name AS department_name
          FROM applications a
          LEFT JOIN locations l   ON l.id = a.location_id
          LEFT JOIN departments d ON d.id = a.owner_department_id
         WHERE a.is_builtin AND (a.module = :m OR a.url = :u)
         ORDER BY a.id
         LIMIT 1
    SQL);
    $st->execute(['m' => $module['module'], 'u' => $module['url']]);
    $application = $st->fetch() ?: [];

    if (wants_json()) {
        $phaseNames = [1 => 'Foundation', 2 => 'Money', 3 => 'Work', 4 => 'Knowledge & ops',
                       5 => 'Agent workforce', 6 => 'Desktop beta'];
        respond_screen(['stub' => [
            'key' => $moduleKey,
            'label' => (string) $module['label'],
            'icon' => (string) ($module['icon'] ?? 'feather-box'),
            'phase' => (int) ($module['phase'] ?? 0),
            'phase_name' => $phaseNames[(int) ($module['phase'] ?? 0)] ?? null,
            'module_grant' => $module['module'] ?? null,
            'url' => (string) ($module['url'] ?? ''),
            'application' => [
                'name' => $application['name'] ?? null,
                'description' => $application['description'] ?? null,
                'category' => $application['category'] ?? null,
                'location_name' => $application['location_name'] ?? null,
                'department_name' => $application['department_name'] ?? null,
            ],
        ]]);
    }

    $pageHtml = view('shared/module-stub.php', [
        'module' => $module,
        'application' => $application,
    ]);
    render_screen($module['label'] . ' · ' . business_name($pdo), $pageHtml, [
        'activeNav' => 'nav-' . $moduleKey,
        'screen' => $screen,
    ]);
    exit;
}
