<?php
declare(strict_types=1);

/** Location form (screens `location-add` / `location-edit`). Gate: require_module_grant('locations'). */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/render.php';

require_module_grant('locations');
estate_require_files();

$pdo = db();
$id = request_integer('id');
$location = [];

if ($id !== null) {
    $location = find_location($pdo, $id);
    if ($location === null) {
        http_response_code(404);
        exit('Location not found.');
    }
} else {
    // The kind param preselects the kind and the parent param preselects the parent, so "add a
    // desk to this office" arrives from location-view with both filled.
    $kind = request_string('kind', 'office');
    $kind = in_array($kind, LOCATION_KINDS, true) ? $kind : 'office';
    $location = [
        'kind' => $kind,
        'parent_location_id' => request_integer('parent'),
        'is_always_on' => $kind === 'office',
    ];
}
$kind = (string) ($location['kind'] ?? 'office');

log_screen_view($pdo, $id === null ? 'location-add' : 'location-edit');
if (wants_json()) {
    require_once dirname(__DIR__, 2) . '/app/features/estate/present.php';
    $named = static fn (string $idKey, string $nameKey): callable
        => static fn (array $r): array => present_named($r, $idKey, $nameKey);
    $platforms = [];
    foreach (LOCATION_PLATFORMS as $p) {
        $platforms[] = ['value' => $p, 'label' => location_platform_label($p)];
    }
    respond_screen([
        'location' => present_location_form($location),
        // Kind decides which parents are offered (buildings for an office, offices for a desk).
        // The HTMX form re-fetched that block from parent-options-fragment.php on every change;
        // here both lists travel once and the form picks.
        'options' => [
            'parents' => [
                'office' => array_map($named('location_id', 'name'), parent_options($pdo, 'office')),
                'desk' => array_map($named('location_id', 'name'), parent_options($pdo, 'desk')),
            ],
            'owners' => array_map($named('member_id', 'display_name'), find_human_member_options($pdo)),
            'platforms' => $platforms,
        ],
        'can' => ['delete' => $id !== null && is_super_admin()],
        'delete_blockers' => $id !== null && is_super_admin() ? array_values(location_delete_blockers($pdo, $id)) : [],
    ]);
}
render_screen(($id === null ? 'New location' : 'Edit location') . ' · ' . business_name($pdo),
    view('estate/location-form.php', [
        'location' => $location,
        'parentOptions' => parent_options($pdo, $kind),
        'ownerOptions' => find_human_member_options($pdo),
        'isEdit' => $id !== null,
        // Only the super-admin may delete, so only the super-admin pays for the check.
        'deleteBlockers' => $id !== null && is_super_admin() ? location_delete_blockers($pdo, $id) : [],
        'errors' => [],
    ]),
    ['activeNav' => 'nav-estate', 'screen' => $id === null ? 'location-add' : 'location-edit',
     'entity' => 'location', 'recordId' => (string) ($id ?? '')]);
