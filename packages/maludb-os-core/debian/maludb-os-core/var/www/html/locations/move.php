<?php
declare(strict_types=1);

/** Action `location_move` — log `location.move`. Gate: mod:locations. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/render.php';
estate_require_files();

require_module_grant('locations');
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('location');
$parentId = request_integer('parent_location');
if ($id === null || ($location = find_location($pdo, $id)) === null) {
    http_response_code(404);
    exit('Location not found.');
}
if ($location['kind'] === 'building' && $parentId !== null) {
    render_location_page($pdo, $id, ['A building has no parent.']);
}
if ($location['kind'] === 'site') {
    render_location_page($pdo, $id, ['A site is a place the business trades from, not a machine: it sits inside nothing.']);
}

check_approval($pdo, 'location_move', 'location.move', 'Move ' . $location['name'],
    ['location' => $id, 'parent_location' => $parentId], 'location', $id);

try {
    $after = move_location($pdo, $id, $parentId);
} catch (PDOException $ex) {
    error_log('location move failed: ' . $ex->getMessage());
    if ($ex->getCode() === 'P0001' && preg_match('/ERROR:\s*(.+?)(\n|$)/s', $ex->getMessage(), $m)) {
        render_location_page($pdo, $id, [trim($m[1])]);
    }
    render_location_page($pdo, $id, ['The location could not be moved.']);
}
if ($after === []) {
    render_location_page($pdo, $id, ['The location could not be moved.']);
}

log_activity($pdo, 'location.move', 'location', $id, [
    'before' => ['parent_location_id' => $location['parent_location_id']],
    'after' => ['parent_location_id' => $after['parent_location_id']],
]);
emit_action_status(true, ['did' => 'Moved ' . $after['name'], 'refresh' => 'locationChanged']);
hx_trigger('locationChanged');
render_location_page($pdo, $id);
