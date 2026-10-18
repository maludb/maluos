<?php
declare(strict_types=1);

/**
 * Action `location_save` — log `location.save` with kind and name in `after`. Gate: mod:locations.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/render.php';
estate_require_files();

require_module_grant('locations');
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('location');

// kind is read-only on edit — a desk does not become a building. The true kind is fetched
// BEFORE parsing the form so validation runs against it, never against whatever the request
// happens to carry for `kind`.
$before = null;
if ($id !== null) {
    $before = find_location($pdo, $id);
    if ($before === null) {
        http_response_code(404);
        exit('Location not found.');
    }
}
[$fields, $errors] = location_fields_from_request($before['kind'] ?? null);

$renderForm = function (array $errs) use ($pdo, $id, $fields): never {
    emit_action_status(false, ['errors' => $errs]);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    echo view('estate/location-form.php', [
        'location' => array_merge($fields, $id !== null ? ['location_id' => $id] : []),
        'parentOptions' => parent_options($pdo, $fields['kind'] ?: 'office'),
        'ownerOptions' => find_human_member_options($pdo),
        'isEdit' => $id !== null,
        'deleteBlockers' => $id !== null && is_super_admin() ? location_delete_blockers($pdo, $id) : [],
        'errors' => $errs,
    ]);
    exit;
};

if ($errors !== []) {
    $renderForm($errors);
}

check_approval($pdo, 'location_save', 'location.save',
    ($id === null ? 'Add location: ' : 'Update location: ') . $fields['name'],
    $fields, 'location', $id);

try {
    $location = $id === null ? insert_location($pdo, $fields) : update_location($pdo, $id, $fields);
} catch (PDOException $ex) {
    error_log('location save failed: ' . $ex->getMessage());
    if ($ex->getCode() === '23505') {
        $renderForm(['A location with that name already exists.']);
    }
    if (str_contains($ex->getMessage(), 'locations_desk_has_owner')) {
        $renderForm(['A desk needs an owner.']);
    }
    if (str_contains($ex->getMessage(), 'locations_building_is_root')) {
        $renderForm(['A building has no parent.']);
    }
    if ($ex->getCode() === 'P0001' && preg_match('/ERROR:\s*(.+?)(\n|$)/s', $ex->getMessage(), $m)) {
        $renderForm([trim($m[1])]);
    }
    $renderForm(['The location could not be saved.']);
}
if ($location === []) {
    $renderForm(['The location could not be saved.']);
}

log_activity($pdo, 'location.save', 'location', (int) $location['location_id'], [
    'before' => $before,
    'after' => ['kind' => $location['kind'], 'name' => $location['name']],
]);
emit_action_status(true, ['did' => ($id === null ? 'Added location ' : 'Updated location ') . $location['name'],
                          'refresh' => 'locationChanged']);
hx_trigger('locationChanged');
render_location_page($pdo, (int) $location['location_id']);
