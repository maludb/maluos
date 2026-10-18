<?php
declare(strict_types=1);

/**
 * Shared re-renders and field parsers for the estate screens — the exemplar's "a write answers
 * with the whole refreshed screen" pattern, so no endpoint assembles a view of its own. Every
 * render_*_page() here emits status: error through the action channel whenever it is called
 * with a non-empty $errors array (the fix the Expenses and Books slices both had to make: a
 * validation error re-rendered with HTTP 200 reads as success to the assistant and to every
 * agent unless X-Action-Status says otherwise).
 */

function estate_require_files(): void
{
    require_once __DIR__ . '/queries.php';
    require_once dirname(__DIR__) . '/team/queries.php';
}

// --------------------------------------------------------------------------
// Locations list
// --------------------------------------------------------------------------
function location_list_filters(): array
{
    return [
        'kind' => request_string('kind'),
        'parent_location_id' => request_integer('parent'),
        'online' => request_bool('online'),
        'status' => request_string('status'),
    ];
}

function render_locations_list(PDO $pdo, array $errors = []): never
{
    estate_require_files();
    if ($errors !== []) {
        emit_action_status(false, ['errors' => $errors]);
    }
    $filters = location_list_filters();
    $rows = find_locations($pdo, $filters, request_string('sort', 'kind'), request_integer('page') ?? 1);
    $total = (int) ($rows[0]['total_count'] ?? 0);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    header('HX-Push-Url: /locations/');
    echo view('estate/locations.php', [
        'locations' => $rows,
        'filters' => $filters,
        'page' => 1,
        'totalPages' => max(1, (int) ceil($total / LOCATION_PAGE_SIZE)),
        'canEdit' => has_module_grant('locations'),
        'errors' => $errors,
    ]);
    exit;
}

// --------------------------------------------------------------------------
// Location detail
// --------------------------------------------------------------------------
function render_location_page(PDO $pdo, int $id, array $errors = []): never
{
    estate_require_files();
    if ($errors !== []) {
        emit_action_status(false, ['errors' => $errors]);
    }
    $location = find_location($pdo, $id);
    if ($location === null) {
        render_locations_list($pdo);
    }
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    header('HX-Push-Url: /locations/' . $id);
    echo view('estate/location.php', [
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
        'errors' => $errors,
    ]);
    exit;
}

// --------------------------------------------------------------------------
// Location form field parsing
// --------------------------------------------------------------------------
/**
 * $existingKind: on edit, the location's true (locked) kind — kind is read-only on edit, so
 * validation must use the record's real kind, never whatever the request happens to carry.
 * Validating against a submitted kind before overriding it with the true one (a form quirk, or
 * a tampered value) would otherwise raise spurious "a desk needs a parent/owner" errors against
 * an office or building being edited.
 */
function location_fields_from_request(?string $existingKind = null): array
{
    $fields = [
        'name' => request_string('name'),
        'kind' => $existingKind ?? request_string('kind'),
        'parent_location_id' => request_integer('parent_location_id'),
        'owner_member_id' => request_integer('owner_member_id'),
        'description' => request_string('description') ?: null,
        'platform' => request_string('platform') ?: null,
        'operating_system' => request_string('operating_system') ?: null,
        'os_version' => request_string('os_version') ?: null,
        // Tri-state: '' means not recorded, which is not the same as No.
        'ssh_access' => request_string('ssh_access') === '' ? null : (request_string('ssh_access') === '1'),
        'root_access' => request_string('root_access') === '' ? null : (request_string('root_access') === '1'),
        'external_ref' => request_string('external_ref') ?: null,
        'hostname' => request_string('hostname') ?: null,
        'ip_address' => request_string('ip_address') ?: null,
        'cpu_cores' => request_integer('cpu_cores'),
        'memory_mb' => request_integer('memory_mb'),
        'storage_gb' => request_integer('storage_gb'),
        'is_always_on' => request_bool('is_always_on'),
        'siting' => request_string('siting') ?: null,
        'address' => request_string('address') ?: null,
        'timezone' => request_string('timezone') ?: null,
    ];

    $errors = [];
    if ($fields['name'] === '' || mb_strlen($fields['name']) > 200) {
        $errors[] = 'A location needs a name (up to 200 characters).';
    }
    if (!in_array($fields['kind'], LOCATION_KINDS, true)) {
        $errors[] = 'Kind is a building, an office, a desk or a site.';
    }
    // A site is a place the business trades from (a restaurant, a shop), not a machine: it has an
    // address and a time zone and nothing else a machine has (db/141).
    if ($fields['kind'] === 'site') {
        $machine = ['parent_location_id', 'owner_member_id', 'platform', 'operating_system', 'os_version',
                    'ssh_access', 'root_access', 'hostname', 'ip_address', 'cpu_cores', 'memory_mb', 'storage_gb'];
        foreach ($machine as $key) {
            if ($fields[$key] !== null) {
                $errors[] = 'A site is a place, not a machine: it has no parent, owner, platform or hardware.';
                break;
            }
        }
        $fields['siting'] = null;
        $fields['is_always_on'] = false;
        if ($fields['timezone'] !== null && !in_array($fields['timezone'], timezone_identifiers_list(), true)) {
            $errors[] = 'That is not a time zone — use a name like America/New_York.';
        }
        if ($fields['address'] !== null && mb_strlen($fields['address']) > 500) {
            $errors[] = 'An address is up to 500 characters.';
        }
        return [$fields, $errors];
    }
    $fields['address'] = null;
    $fields['timezone'] = null;
    if ($fields['kind'] === 'building' && $fields['parent_location_id'] !== null) {
        $errors[] = 'A building has no parent.';
    }
    if ($fields['kind'] === 'office' && $fields['owner_member_id'] !== null) {
        $fields['owner_member_id'] = null; // owner is a desk-only concept
    }
    if ($fields['kind'] === 'desk' && $fields['parent_location_id'] === null) {
        $errors[] = 'A desk needs a parent office.';
    }
    if ($fields['kind'] === 'desk' && $fields['owner_member_id'] === null) {
        $errors[] = 'A desk needs an owner.';
    }
    // Siting is required for an office or desk; a building has none of its own — it IS the host.
    if ($fields['kind'] === 'building') {
        $fields['siting'] = null;
    } elseif (!in_array($fields['siting'], LOCATION_SITINGS, true)) {
        $errors[] = 'An office or desk must say whether it is onsite or offsite.';
    }
    if ($fields['platform'] !== null && !in_array($fields['platform'], LOCATION_PLATFORMS, true)) {
        $errors[] = 'That is not a platform this app knows.';
    }
    // Validated in PHP with filter_var() so a typo is a field error, not a Postgres cast error.
    if ($fields['ip_address'] !== null && filter_var($fields['ip_address'], FILTER_VALIDATE_IP) === false) {
        $errors[] = 'That is not a valid IP address.';
    }
    foreach (['cpu_cores' => 'CPU cores', 'memory_mb' => 'Memory', 'storage_gb' => 'Storage'] as $key => $label) {
        if ($fields[$key] !== null && $fields[$key] <= 0) {
            $errors[] = $label . ' must be more than zero.';
        }
    }

    return [$fields, $errors];
}
