<?php
declare(strict_types=1);

/** Location detail (screen `location-view`). Gate: insider — reading the estate is open to anyone who works here; changing it needs mod:locations. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/render.php';

require_insider();   // reading the estate is insider-open (mcp_locations = app_is_insider); changing it needs the grant
estate_require_files();

$pdo = db();
$id = request_integer('id');
if ($id === null || ($location = find_location($pdo, $id)) === null) {
    http_response_code(404);
    exit('Location not found.');
}

log_screen_view($pdo, 'location-view');
if (wants_json()) {
    require_once dirname(__DIR__, 2) . '/app/features/estate/present.php';
    require_once dirname(__DIR__, 2) . '/app/features/records/present.php';
    $isDesk = $location['kind'] === 'desk';
    $isOwner = $isDesk && (int) ($location['owner_member_id'] ?? 0) === (int) current_member_id();
    $blockers = is_super_admin() ? location_delete_blockers($pdo, $id) : [];
    respond_screen([
        'location' => present_location($location),
        'residents' => array_map('present_location_resident', find_location_residents($pdo, $id)),
        'departments' => array_map(static fn (array $d): array => present_named($d, 'department_id', 'name'),
            find_location_departments($pdo, $id)),
        'applications' => array_map('present_location_application', find_location_applications($pdo, $id)),
        // A site runs nothing; it is served by the scoped applications that list it (db/141).
        'serving_applications' => array_map(static fn (array $a): array => [
            'id' => (int) $a['application_id'], 'name' => (string) $a['application_name'],
            'scope_id' => (int) $a['scope_id'], 'live_grant_count' => (int) $a['live_grant_count'],
        ], find_location_serving_applications($pdo, $id)),
        'options' => [
            'residents' => array_map('present_member_option', selectable_members($pdo)),
            'departments' => array_map('present_department_option', find_departments($pdo)),
            'agents' => array_map(static fn (array $a): array => present_named($a, 'member_id', 'display_name'),
                find_agent_profile_options($pdo)),
            'buildings' => array_map(static fn (array $b): array => present_named($b, 'location_id', 'name'),
                parent_options($pdo, 'office')),
        ],
        // The template asked is_super_admin() and compared the owner inline; the answers travel.
        'can' => [
            'retire' => $location['status'] === 'active' && (($isDesk && $isOwner) || is_super_admin()),
            'delete' => is_super_admin(),
        ],
        'delete_blockers' => array_values($blockers),
    ]);
}
render_screen(($location['name'] ?? 'Location') . ' · ' . business_name($pdo),
    view('estate/location.php', [
        'location' => $location,
        'residents' => find_location_residents($pdo, $id),
        'departments' => find_location_departments($pdo, $id),
        'applications' => find_location_applications($pdo, $id),
        'selectableResidents' => selectable_members($pdo),
        'selectableDepartments' => find_departments($pdo),
        'agentOptions' => find_agent_profile_options($pdo),
        'buildingOptions' => parent_options($pdo, 'office'),
        'isAdmin' => is_business_admin(),
        'myId' => (int) current_member_id(),
        // Only the super-admin may delete, so only the super-admin pays for the check.
        'deleteBlockers' => is_super_admin() ? location_delete_blockers($pdo, $id) : [],
        'errors' => [],
    ]),
    ['activeNav' => 'nav-estate', 'screen' => 'location-view', 'entity' => 'location', 'recordId' => (string) $id]);
