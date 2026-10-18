<?php
declare(strict_types=1);

/**
 * Work Locations (screen `locations-list`) — every building, office and desk as one table.
 * This is the Work Locations screen in the nav: the tree map that used to live at `/estate/`
 * was replaced by this table on 2026-09-18, and that URL now redirects here.
 *
 * Gate: insider — reading the estate is open to anyone who works here; changing it needs
 * mod:locations, which is also what decides whether the table offers its Edit column.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/render.php';

require_insider();   // reading the estate is insider-open (mcp_locations = app_is_insider); changing it needs the grant
estate_require_files();

$pdo = db();
$filters = location_list_filters();
$page = request_integer('page') ?? 1;
$locations = find_locations($pdo, $filters, request_string('sort', 'kind'), $page);
$total = (int) ($locations[0]['total_count'] ?? 0);
$data = [
    'locations' => $locations,
    'filters' => $filters,
    'page' => $page,
    'totalPages' => max(1, (int) ceil($total / LOCATION_PAGE_SIZE)),
    'canEdit' => has_module_grant('locations'),
];

if (wants_json()) {
    require_once dirname(__DIR__, 2) . '/app/features/estate/present.php';
    log_screen_view($pdo, 'locations-list');
    respond_screen([
        'locations' => array_map('present_location_row', $locations),
        'pagination' => ['page' => $page, 'total_pages' => $data['totalPages'], 'total' => $total],
        'filters' => [
            'kind' => (string) $filters['kind'],
            'parent' => $filters['parent_location_id'] === null ? '' : (string) $filters['parent_location_id'],
            'online' => (bool) $filters['online'],
            'retired' => $filters['status'] === 'retired',
        ],
        'can' => ['edit' => $data['canEdit']],
    ]);
}

if (($_SERVER['HTTP_HX_TARGET'] ?? '') === 'locations-list-results') {
    header('Vary: HX-Request');
    echo view('estate/partials/location-table.php', $data);
    exit;
}

log_screen_view($pdo, 'locations-list');
render_screen('Work Locations · ' . business_name($pdo), view('estate/locations.php', $data),
    ['activeNav' => 'nav-estate', 'screen' => 'locations-list']);
