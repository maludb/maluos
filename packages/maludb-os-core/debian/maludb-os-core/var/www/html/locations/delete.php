<?php
declare(strict_types=1);

/**
 * Action `location_delete` — log `location.delete`. Gate: `super` — the super-admin only.
 *
 * Retiring is the normal end of a location's life: it keeps the row, its specs and everything
 * that happened there. Deleting is for the row that should never have existed — a mistyped
 * desk, a duplicate office — and it is refused the moment anything still points at the
 * location, so history is never deleted by way of the thing it happened to.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/render.php';
estate_require_files();

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('location');
if ($id === null || ($location = find_location($pdo, $id)) === null) {
    http_response_code(404);
    exit('Location not found.');
}

check_approval($pdo, 'location_delete', 'location.delete', 'Delete ' . $location['name'],
    ['location' => $id], 'location', $id);

try {
    $deleted = delete_location($pdo, $id);
} catch (RuntimeException $ex) {
    render_location_page($pdo, $id, [$ex->getMessage()]);
}
if (!$deleted) {
    render_location_page($pdo, $id, ['The location could not be deleted.']);
}

// The row is gone, so the log carries what it was: an id alone would name nothing afterwards.
log_activity($pdo, 'location.delete', 'location', $id, [
    'before' => [
        'name' => $location['name'], 'kind' => $location['kind'], 'status' => $location['status'],
        'parent_location_id' => $location['parent_location_id'], 'siting' => $location['siting'] ?? null,
        'hostname' => $location['hostname'] ?? null,
    ],
]);
emit_action_status(true, ['did' => 'Deleted ' . $location['name'], 'refresh' => 'locationChanged']);
hx_trigger('locationChanged');
render_locations_list($pdo);
