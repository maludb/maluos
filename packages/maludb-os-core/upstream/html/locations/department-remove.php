<?php
declare(strict_types=1);

/**
 * Action `location_remove_department` — log `department.set_home_location`. Gate: `mod:locations,
 * admin` (OR) — same reasoning as department-add.php. This is the manifest's own row (base
 * `/locations/department-remove.php`); it already exists there, answering the spec's "the
 * manifest has an add with no remove" — it does not, so nothing is added to the manifest here.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/render.php';
estate_require_files();

require_module('locations');
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('location');
$departmentId = request_integer('department');
if ($id === null || $departmentId === null || ($location = find_location($pdo, $id)) === null) {
    http_response_code(404);
    exit('Location not found.');
}
$department = find_department($pdo, $departmentId);
if ($department === null) {
    http_response_code(404);
    exit('Department not found.');
}

check_approval($pdo, 'location_remove_department', 'department.set_home_location',
    'Remove ' . $department['name'] . '\'s home at ' . $location['name'],
    ['location' => $id, 'department' => $departmentId], 'department', $departmentId);

$after = set_department_home($pdo, $departmentId, null);
if ($after === []) {
    render_location_page($pdo, $id, ['That department\'s home could not be removed.']);
}

log_activity($pdo, 'department.set_home_location', 'department', $departmentId, [
    'before' => ['home_location_id' => $id],
    'after' => ['home_location_id' => null],
]);
emit_action_status(true, ['did' => 'Removed ' . $after['name'] . '\'s home at ' . $location['name'],
                          'refresh' => 'locationChanged']);
hx_trigger('locationChanged');
render_location_page($pdo, $id);
