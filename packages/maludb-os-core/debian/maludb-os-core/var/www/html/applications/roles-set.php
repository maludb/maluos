<?php
declare(strict_types=1);

/**
 * Action `application_roles_set` — log `application.roles_set`. Gate: super-admin. An application's
 * own roles (db/141), as its maludb-os.json declares them: `roles` is a JSON list of
 * {key, name, capability, is_admin} that replaces the declared list, in order. Each role amounts to a
 * kernel capability; exactly one is the admin role, the one a super-admin holds everywhere. A role held
 * by a live grant cannot be dropped. Undo: set the previous list (the log's `before`).
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

$raw = json_decode(request_string('roles'), true);
if (!is_array($raw) || !array_is_list($raw)) {
    $refuse(['Roles are a list: [{"key": "admin", "name": "Admin", "capability": "admin", "is_admin": true}, …] — an empty list removes them all.']);
}
$roles = [];
$errors = [];
foreach ($raw as $r) {
    $key = is_array($r) ? strtolower(trim((string) ($r['key'] ?? ''))) : '';
    $role = [
        'key' => $key,
        'name' => is_array($r) ? trim((string) ($r['name'] ?? '')) : '',
        'capability' => is_array($r) ? (string) ($r['capability'] ?? '') : '',
        'is_admin' => is_array($r) && !empty($r['is_admin']),
    ];
    if (!preg_match('/^[a-z][a-z0-9_]{0,39}$/', $key)) {
        $errors[] = 'A role key is lowercase letters, digits and underscores, starting with a letter: ' . ($key ?: '(empty)') . '.';
    } elseif (isset($roles[$key])) {
        $errors[] = 'The role ' . $key . ' is listed twice.';
    }
    if ($role['name'] === '' || mb_strlen($role['name']) > 100) {
        $errors[] = 'The role ' . ($key ?: '?') . ' needs a name (up to 100 characters).';
    }
    if (!in_array($role['capability'], ACCESS_CAPABILITIES, true)) {
        $errors[] = 'The role ' . ($key ?: '?') . ' amounts to read, write or admin.';
    }
    if ($role['is_admin'] && $role['capability'] !== 'admin') {
        $errors[] = 'The admin role amounts to admin.';
    }
    $roles[$key] = $role;
}
$admins = count(array_filter($roles, static fn (array $r): bool => $r['is_admin']));
if ($roles !== [] && $admins !== 1) {
    $errors[] = 'Exactly one role is the admin role — the one a super-admin holds everywhere.';
}
if ($errors !== []) {
    $refuse(array_values(array_unique($errors)));
}

$before = array_map(static fn (array $r): array => ['key' => $r['role_key'], 'name' => $r['name'],
    'capability' => $r['capability'], 'is_admin' => (bool) $r['is_admin']], find_application_roles($pdo, $id));

check_approval($pdo, 'application_roles_set', 'application.roles_set',
    'Set the roles of ' . $application['name'] . ': ' . (implode(', ', array_keys($roles)) ?: 'none'),
    ['application' => $id, 'roles' => array_values($roles)], 'application', $id);

try {
    $pdo->beginTransaction();
    set_application_roles($pdo, $id, array_values($roles));
    log_activity($pdo, 'application.roles_set', 'application', $id, [
        'before' => ['roles' => $before],
        'after' => ['roles' => array_values($roles)],
    ]);
    $pdo->commit();
} catch (PDOException $ex) {
    $pdo->rollBack();
    error_log('application roles set failed: ' . $ex->getMessage());
    $refuse([application_trigger_message($ex, 'The roles could not be saved.')]);
}

$did = 'Set the roles of ' . $application['name'] . ': ' . (implode(', ', array_keys($roles)) ?: 'none');
emit_action_status(true, ['did' => $did, 'refresh' => 'applicationChanged']);
if (wants_json()) {
    respond_saved(['did' => $did, 'location' => '/applications/' . $id]);
}
render_application_page($pdo, $id, 'overview');
