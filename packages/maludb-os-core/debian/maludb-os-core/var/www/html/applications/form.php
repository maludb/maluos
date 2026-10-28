<?php
declare(strict_types=1);

/** Application form (screens `application-add` / `application-edit`). Gate: require_module_grant('applications'). */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';

require_module_grant('applications');
applications_require_files();

$pdo = db();
$id = request_integer('id');
$application = [];

if ($id !== null) {
    $application = find_application($pdo, $id);
    if ($application === null) {
        http_response_code(404);
        exit('Application not found.');
    }
} else {
    // Registering from the inventory: the catalog entry says what it is and where it belongs.
    $entry = request_string('catalog') !== '' ? find_catalog_entry($pdo, request_string('catalog')) : null;
    if ($entry !== null && $entry['kind'] !== 'external') {
        $entry = null;   // a built-in is turned on in Settings → Navigation, never registered twice
    }
    $application = [
        'name' => $entry['name'] ?? '',
        'app_key' => $entry['catalog_key'] ?? null,
        'catalog_key' => $entry['catalog_key'] ?? null,
        'description' => $entry['description'] ?? null,
        'vendor' => $entry['vendor'] ?? null,
        'business_area_id' => $entry['business_area_id'] ?? null,
        'business_area_name' => $entry['business_area_name'] ?? null,
        'category' => $entry['category'] ?? (request_string('category') ?: null),
        'location_id' => request_integer('location'),
        'owner_department_id' => request_integer('department'),
        'is_self_hosted' => $entry === null,
        'criticality' => 'normal',
    ];
}

log_screen_view($pdo, $id === null ? 'application-add' : 'application-edit');
if (wants_json()) {
    require_once dirname(__DIR__, 2) . '/app/features/applications/present.php';
    require_once dirname(__DIR__, 2) . '/app/features/records/present.php';
    $categories = [];
    foreach (APPLICATION_CATEGORIES as $c) {
        $categories[] = ['value' => $c, 'label' => application_category_label($c)];
    }
    respond_screen([
        'application' => present_application($application),
        'options' => [
            'categories' => $categories,
            'criticalities' => APPLICATION_CRITICALITIES,
            'areas' => array_map(static fn (array $g): array => [
                'id' => (int) $g['business_area_id'], 'name' => business_area_label($g['name'])], find_business_areas($pdo)),
            'locations' => array_map(static fn (array $l): array
                => ['id' => (int) $l['location_id'], 'name' => $l['name'] . ' (' . ucfirst((string) $l['kind']) . ')'],
                application_location_options($pdo)),
            'departments' => array_map('present_department_option', find_departments($pdo)),
            'owners' => array_map(static fn (array $m): array
                => ['id' => (int) $m['member_id'], 'name' => (string) $m['display_name']], application_owner_options($pdo)),
        ],
    ]);
}
render_screen(($id === null ? 'New application' : 'Edit application') . ' · ' . business_name($pdo),
    view('applications/application-form.php', [
        'application' => $application,
        'locationOptions' => application_location_options($pdo),
        'departmentOptions' => find_departments($pdo),
        'ownerOptions' => application_owner_options($pdo),
        'isEdit' => $id !== null,
        'errors' => [],
    ]),
    ['activeNav' => 'nav-applications', 'screen' => $id === null ? 'application-add' : 'application-edit',
     'entity' => 'application', 'recordId' => (string) ($id ?? '')]);
