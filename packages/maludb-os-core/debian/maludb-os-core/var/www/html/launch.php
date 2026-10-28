<?php
declare(strict_types=1);

/**
 * Screen `launch` (GET /launch.php?application=<id>) — carry this person into an application from
 * us, signed in (A3, 2026-09-22; docs/build-specs/kernel-sign-on.md). The React route
 * /launch/<id> asks this in JSON mode and sends the browser to `location`; a browser reaching it
 * directly is redirected. `&scope=<scope id>` opens a scoped application at one of the person's
 * sites or departments (db/141). Refused, in the handler's own words: an agent (its credential is a run
 * token on MCP), an application the person holds no live grant on, one that is not active, or
 * one with no address or no sso path — those the launcher opens as they are.
 */
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/applications/queries.php';
require_once dirname(__DIR__) . '/app/features/applications/sso.php';

require_login();

$pdo = db();
$member = current_member();
$id = request_integer('application');
$refuse = static function (string $message, int $status = 422): never {
    emit_action_status(false, ['errors' => [$message]]);
    if (wants_json()) {
        json_error($status === 404 ? 'not_found' : ($status === 403 ? 'forbidden' : 'invalid'), $message, $status);
    }
    http_response_code($status);
    exit(e($message));
};
if ($id === null) {
    $refuse('Which application?', 404);
}
if (($member['member_kind'] ?? 'human') !== 'human') {
    $refuse('An agent reaches an application through MCP with its run token, never the launcher.', 403);
}
$st = $pdo->prepare('SELECT application_id, name, app_key, url, status, capability, sso_path, scope_kind FROM mcp_my_applications WHERE application_id = :id');
$st->execute(['id' => $id]);
$application = $st->fetch() ?: null;
if ($application === null || $application['capability'] === null) {
    $refuse('Application not found.', 404);           // or not yours to open — the same sentence, on purpose
}
if ($application['status'] !== 'active') {
    $refuse('This application is ' . $application['status'] . '.');
}
if (($application['url'] ?? '') === '' || !preg_match('#^https?://#i', (string) $application['url'])) {
    $refuse('No address is recorded for this application.');
}
if (($application['sso_path'] ?? '') === '') {
    $refuse('This application does not take the platform\'s sign-on yet. Open it from its own address.');
}

// A scoped application (db/141): the person carries every scope they hold, and the one they chose.
// A scope they do not hold is refused with the same sentence as an application they cannot see.
$holding = sso_member_holding($pdo, (int) $application['application_id'], (int) $member['id']);
$scope = request_integer('scope');
$held = array_column($holding['scopes'], 'scope_id');
if ($scope !== null && !in_array($scope, $held, true)) {
    $refuse('Application not found.', 404);
}
if ($application['scope_kind'] !== 'none' && $held === []) {
    $refuse('Application not found.', 404);
}
if ($scope === null && count($held) === 1) {
    $scope = $held[0];
}
$location = sso_launch_url($pdo, $application, $member, (string) $application['capability'], $holding, $scope);
$_SESSION['sso_apps'][(int) $application['application_id']] = (string) $application['app_key'];
log_activity($pdo, 'application.sign_on', 'application', (int) $application['application_id'],
    ['after' => ['app_key' => $application['app_key'], 'capability' => $application['capability'],
                 'role' => $holding['role'], 'scope_id' => $scope]]);
emit_action_status(true, ['did' => 'Opened ' . $application['name'] . ' signed in']);
if (wants_json()) {
    respond_screen(['location' => $location, 'application' => ['id' => (int) $application['application_id'], 'name' => (string) $application['name']]]);
}
header('Location: ' . $location, true, 302);
exit;
