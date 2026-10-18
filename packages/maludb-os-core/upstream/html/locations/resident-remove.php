<?php
declare(strict_types=1);

/** Action `location_remove_resident` — log `location_resident.remove`. Gate: mod:locations. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/render.php';
estate_require_files();

require_module_grant('locations');
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('location');
$memberId = request_integer('member');
if ($id === null || $memberId === null || ($location = find_location($pdo, $id)) === null) {
    http_response_code(404);
    exit('Location not found.');
}

check_approval($pdo, 'location_remove_resident', 'location_resident.remove',
    'Remove a resident from ' . $location['name'],
    ['location' => $id, 'member' => $memberId], 'location', $id);

remove_location_resident($pdo, $id, $memberId);
log_activity($pdo, 'location_resident.remove', 'location', $id, [
    'before' => ['member_id' => $memberId],
]);
emit_action_status(true, ['did' => 'Removed resident from ' . $location['name'], 'refresh' => 'locationChanged']);
hx_trigger('locationChanged');
render_location_page($pdo, $id);
