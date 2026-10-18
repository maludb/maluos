<?php
declare(strict_types=1);

/**
 * Action `location_rename` — log `location.rename`. Gate: `desk owner, admin` — a comma in the
 * manifest's Who column means OR: the owner of that desk, OR a business admin. Not mod:locations
 * — an ordinary desk owner with no grant may still rename their own desk.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/render.php';
estate_require_files();

require_login();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('location');
$name = request_string('name');
if ($id === null || ($location = find_location($pdo, $id)) === null) {
    http_response_code(404);
    exit('Location not found.');
}
$isOwner = $location['kind'] === 'desk' && (int) ($location['owner_member_id'] ?? 0) === (int) current_member_id();
if (!$isOwner && !is_business_admin()) {
    deny('Only this desk\'s owner, or an administrator, may rename it.');
}
if ($name === '' || mb_strlen($name) > 200) {
    render_location_page($pdo, $id, ['A location needs a name (up to 200 characters).']);
}

check_approval($pdo, 'location_rename', 'location.rename', 'Rename ' . $location['name'] . ' to ' . $name,
    ['location' => $id, 'name' => $name], 'location', $id);

try {
    $after = rename_location($pdo, $id, $name);
} catch (PDOException $ex) {
    error_log('location rename failed: ' . $ex->getMessage());
    if ($ex->getCode() === '23505') {
        render_location_page($pdo, $id, ['A location with that name already exists.']);
    }
    render_location_page($pdo, $id, ['The location could not be renamed.']);
}
if ($after === []) {
    render_location_page($pdo, $id, ['The location could not be renamed.']);
}

log_activity($pdo, 'location.rename', 'location', $id, [
    'before' => ['name' => $location['name']],
    'after' => ['name' => $after['name']],
]);
emit_action_status(true, ['did' => 'Renamed to ' . $after['name'], 'refresh' => 'locationChanged']);
hx_trigger('locationChanged');
render_location_page($pdo, $id);
