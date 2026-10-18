<?php
declare(strict_types=1);

/**
 * Action `location_add_department` — log `department.set_home_location`. Gate: `mod:locations,
 * admin` — a comma means OR, and here `has_module()` already computes exactly that (it admits
 * any business admin in addition to a grant holder), so require_module() is the right gate for
 * these two department actions — unlike every other endpoint in this slice, which uses the
 * stricter require_module_grant() because mcp_locations has no department to scope an admin by.
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
if ($location['kind'] !== 'office') {
    render_location_page($pdo, $id, ['Only an office can be a department\'s home.']);
}
$department = find_department($pdo, $departmentId);
if ($department === null) {
    http_response_code(404);
    exit('Department not found.');
}

check_approval($pdo, 'location_add_department', 'department.set_home_location',
    'Give ' . $department['name'] . ' its home at ' . $location['name'],
    ['location' => $id, 'department' => $departmentId], 'department', $departmentId);

$after = set_department_home($pdo, $departmentId, $id);
if ($after === []) {
    render_location_page($pdo, $id, ['That department could not be given a home here.']);
}

log_activity($pdo, 'department.set_home_location', 'department', $departmentId, [
    'before' => ['home_location_id' => $department['home_location_id']],
    'after' => ['home_location_id' => $id],
]);
emit_action_status(true, ['did' => 'Gave ' . $after['name'] . ' its home at ' . $location['name'],
                          'refresh' => 'locationChanged']);
hx_trigger('locationChanged');
render_location_page($pdo, $id);
