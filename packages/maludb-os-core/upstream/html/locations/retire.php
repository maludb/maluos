<?php
declare(strict_types=1);

/**
 * Action `location_retire` — log `location.retire`. Gate: `desk owner, super` — a comma means
 * OR: the desk's owner_member_id, OR a super-admin. Getting this backwards locks the owner out
 * of their own desk (the spec's own warning). For a building or office (no owner_member_id at
 * all) only a super-admin may retire it.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/render.php';
estate_require_files();

require_login();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('location');
if ($id === null || ($location = find_location($pdo, $id)) === null) {
    http_response_code(404);
    exit('Location not found.');
}
$isOwner = $location['kind'] === 'desk' && (int) ($location['owner_member_id'] ?? 0) === (int) current_member_id();
if (!$isOwner && !is_super_admin()) {
    deny('Only this desk\'s owner, or the super-admin, may retire it.');
}

check_approval($pdo, 'location_retire', 'location.retire', 'Retire ' . $location['name'],
    ['location' => $id], 'location', $id);

try {
    $after = retire_location($pdo, $id);
} catch (RuntimeException $ex) {
    render_location_page($pdo, $id, [$ex->getMessage()]);
}
if ($after === []) {
    render_location_page($pdo, $id, ['The location could not be retired.']);
}

log_activity($pdo, 'location.retire', 'location', $id, [
    'before' => ['status' => $location['status'], 'kind' => $location['kind'], 'name' => $location['name']],
    'after' => ['status' => $after['status']],
]);
emit_action_status(true, ['did' => 'Retired ' . $after['name'], 'refresh' => 'locationChanged']);
hx_trigger('locationChanged');
render_locations_list($pdo);
