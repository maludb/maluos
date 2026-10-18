<?php
declare(strict_types=1);

/**
 * Applications inventory (screen `applications-list`): every application the business could run,
 * grouped by business area, the running ones highlighted (db/130). Gate: insider — reading the
 * registry is open to anyone who works here; changing it needs mod:applications. JSON only: the
 * cards were born after the React cut-over.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/present.php';
require_once dirname(__DIR__, 2) . '/app/features/records/present.php';   // present_department_option()

require_insider();
applications_require_files();

$pdo = db();
log_screen_view($pdo, 'applications-list');

$filters = [
    'business_area_id' => request_integer('area'),
    'owner_department_id' => request_integer('department'),
    'health' => request_string('health'),
    'gaps' => request_bool('gaps'),
    'active' => request_bool('active'),
    'retired' => request_bool('retired'),
];
$q = request_string('q');
// A department, a health or a gap belongs to something registered: asking for one leaves the
// merely available entries out, and so does "running only".
$registeredOnly = $filters['owner_department_id'] !== null || $filters['health'] !== ''
    || $filters['gaps'] || $filters['active'];

// "Open" launches the application itself — only where the launcher would offer it to this person
// (find_launchable_applications(): active, a real address, a site held when split by site).
$openPaths = [];
foreach (find_launchable_applications($pdo) as $l) {
    $openPaths[(int) $l['application_id']] = application_open_path($l);
}

$cards = [];
foreach (find_application_inventory($pdo, $filters) as $a) {
    $gaps = $filters['gaps'] ? application_gaps($pdo, (int) $a['application_id']) : [];
    $card = present_application_card($a, $gaps);
    $card['open_url'] = $openPaths[(int) $a['application_id']] ?? null;
    if ($filters['active'] && $card['state'] !== 'active') {
        continue;
    }
    $cards[] = [$a['business_area_id'] === null ? null : (int) $a['business_area_id'], $card];
}
if (!$registeredOnly) {
    foreach (find_available_catalog_entries($pdo, $filters['business_area_id']) as $c) {
        $cards[] = [(int) $c['business_area_id'], present_catalog_card($c)];
    }
}
$areas = find_business_areas($pdo);
$inventory = present_application_inventory($areas, $cards, $q);
$shown = count($inventory['running']) + array_sum(array_map(static fn (array $a): int => count($a['applications']), $inventory['areas']));

// The React page of 2026-09-28 asks for ?layout=running; the build before it read the running cards inside
// their areas with an active_count, so without the parameter they are folded back (until that build is gone).
if (request_string('layout') !== 'running') {
    foreach ($inventory['running'] as $card) {
        $at = null;
        foreach ($inventory['areas'] as $i => $a) { if ($a['name'] === $card['business_area']) { $at = $i; } }
        if ($at === null) {
            $inventory['areas'][] = ['id' => null, 'name' => $card['business_area'], 'applications' => []];
            $at = array_key_last($inventory['areas']);
        }
        $inventory['areas'][$at]['applications'][] = $card;
    }
    foreach ($inventory['areas'] as &$a) {
        usort($a['applications'], static fn (array $x, array $y): int => ($x['state'] === 'active' ? 0 : 1) <=> ($y['state'] === 'active' ? 0 : 1) ?: strcasecmp($x['name'], $y['name']));
        $a['active_count'] = count(array_filter($a['applications'], static fn (array $c): bool => $c['state'] === 'active'));
    }
    unset($a);
    $inventory['running'] = [];
}

respond_screen([
    'running' => $inventory['running'],
    'areas' => $inventory['areas'],
    'counts' => ['active' => count($inventory['running']), 'total' => $shown],
    'filters' => [
        'q' => $q,
        'area' => $filters['business_area_id'] === null ? '' : (string) $filters['business_area_id'],
        'department' => $filters['owner_department_id'] === null ? '' : (string) $filters['owner_department_id'],
        'health' => (string) $filters['health'],
        'gaps' => (bool) $filters['gaps'],
        'active' => (bool) $filters['active'],
        'retired' => (bool) $filters['retired'],
    ],
    'options' => [
        'areas' => array_map(static fn (array $g): array => [
            'id' => (int) $g['business_area_id'], 'name' => business_area_label($g['name'])], $areas),
        'departments' => array_map('present_department_option', find_departments($pdo)),
    ],
    'can' => ['edit' => can_edit_applications($pdo), 'arrange_menu' => is_super_admin()],
]);
