<?php
declare(strict_types=1);

/** Action `location_add_resident` — log `location_resident.create`. Gate: mod:locations. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/render.php';
estate_require_files();

require_module_grant('locations');
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('location');
$memberId = request_integer('member');
$isPrimary = request_bool('is_primary');
if ($id === null || $memberId === null || ($location = find_location($pdo, $id)) === null) {
    http_response_code(404);
    exit('Location not found.');
}

check_approval($pdo, 'location_add_resident', 'location_resident.create',
    'Add a resident to ' . $location['name'],
    ['location' => $id, 'member' => $memberId, 'is_primary' => $isPrimary], 'location', $id);

try {
    $row = add_location_resident($pdo, $id, $memberId, $isPrimary);
} catch (PDOException $ex) {
    error_log('add resident failed: ' . $ex->getMessage());
    render_location_page($pdo, $id, ['That resident could not be added.']);
}
if ($row === []) {
    render_location_page($pdo, $id, ['That resident could not be added.']);
}

log_activity($pdo, 'location_resident.create', 'location', $id, [
    'after' => ['member_id' => $memberId, 'is_primary' => $isPrimary],
]);
emit_action_status(true, ['did' => 'Added resident to ' . $location['name'], 'refresh' => 'locationChanged']);
hx_trigger('locationChanged');
render_location_page($pdo, $id);
