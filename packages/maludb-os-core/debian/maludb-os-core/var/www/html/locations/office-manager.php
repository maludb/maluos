<?php
declare(strict_types=1);

/**
 * Action `location_set_office_manager` — log `location.set_office_manager`. Gate: mod:locations.
 * The picker is over agent_profiles(member_id); until Agent HR ships there are no agent
 * profiles, so `agent` is always empty and this clears the office manager rather than setting one.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/render.php';
estate_require_files();

require_module_grant('locations');
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('location');
$agentId = request_integer('agent');
if ($id === null || ($location = find_location($pdo, $id)) === null) {
    http_response_code(404);
    exit('Location not found.');
}
if ($location['kind'] !== 'office') {
    render_location_page($pdo, $id, ['Only an office has an office manager.']);
}

check_approval($pdo, 'location_set_office_manager', 'location.set_office_manager',
    'Set office manager for ' . $location['name'],
    ['location' => $id, 'agent' => $agentId], 'location', $id);

try {
    $after = set_office_manager($pdo, $id, $agentId);
} catch (PDOException $ex) {
    error_log('set office manager failed: ' . $ex->getMessage());
    render_location_page($pdo, $id, ['That is not a valid office manager.']);
}
if ($after === []) {
    render_location_page($pdo, $id, ['The office manager could not be set.']);
}

log_activity($pdo, 'location.set_office_manager', 'location', $id, [
    'before' => ['office_manager_member_id' => $location['office_manager_member_id']],
    'after' => ['office_manager_member_id' => $after['office_manager_member_id']],
]);
emit_action_status(true, ['did' => 'Set office manager for ' . $after['name'], 'refresh' => 'locationChanged']);
hx_trigger('locationChanged');
render_location_page($pdo, $id);
