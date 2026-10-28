<?php
declare(strict_types=1);

/**
 * Action `application_roles_refresh` — log `application.roles_refresh`. Gate: super.
 *
 * Reads the application's roles from the application itself — the `app_roles` tool on its MCP server,
 * called with a 60-second kernel token (app/features/applications/roles.php, db/145) — and makes the
 * kernel's copy match: new roles added, changed ones updated, a role no longer published withdrawn
 * (never deleted: the grants still holding it are listed on the Access tab until they are changed).
 * Every holder's rights go out again on the directory change feed. Undo: refresh again after the
 * application changes back. Born after the cut-over: no template, so a refusal says its own words.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';
applications_require_files();

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$refuse = static function (array $errors): never {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);
};
$id = request_integer('application');
if ($id === null || ($application = find_application($pdo, $id)) === null) {
    emit_action_status(false, ['errors' => ['Application not found.']]);
    json_error('not_found', 'Application not found.', 404);
}

check_approval($pdo, 'application_roles_refresh', 'application.roles_refresh',
    'Read the roles of ' . $application['name'] . ' from the application', ['application' => $id], 'application', $id);

try {
    [$payload, $endpoint] = fetch_application_roles($pdo, $application);
} catch (RuntimeException $ex) {
    $refuse([$ex->getMessage()]);
}
[$roles, $errors] = validate_application_roles($payload);
if ($errors !== []) {
    $refuse(array_map(static fn (string $e): string => $application['name'] . ': ' . $e, array_values(array_unique($errors))));
}

$before = array_map(static fn (array $r): array => ['key' => $r['role_key'], 'name' => $r['name'], 'capability' => $r['capability'],
    'is_admin' => (bool) $r['is_admin'], 'withdrawn' => $r['withdrawn_at'] !== null], find_application_roles($pdo, $id));
try {
    $pdo->beginTransaction();
    $outcome = apply_application_roles($pdo, $id, $roles);
    log_activity($pdo, 'application.roles_refresh', 'application', $id, [
        'before' => ['roles' => $before],
        'after' => ['endpoint' => $endpoint, 'roles' => array_map(static fn (array $r): array => [
            'key' => $r['key'], 'name' => $r['name'], 'capability' => $r['capability'], 'is_admin' => $r['is_admin'],
            'rights' => array_column($r['rights'], 'key')], $roles)] + $outcome,
    ]);
    $pdo->commit();
} catch (PDOException $ex) {
    $pdo->rollBack();
    $refuse([application_trigger_message($ex, 'The roles could not be saved.')]);
}

$said = [];
foreach (['added' => 'added', 'changed' => 'changed', 'withdrawn' => 'withdrawn', 'restored' => 'offered again'] as $k => $word) {
    if ($outcome[$k] !== []) {
        $said[] = $word . ' ' . implode(', ', $outcome[$k]);
    }
}
emit_action_status(true, ['did' => 'Read ' . count($roles) . ' roles from ' . $application['name']
                          . ($said === [] ? ' — nothing changed' : ' — ' . implode('; ', $said)),
                          'refresh' => 'applicationChanged']);
hx_trigger('applicationChanged');
