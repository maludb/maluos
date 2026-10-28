<?php
declare(strict_types=1);

/**
 * /api/v1/directory/departments.php — the departments (A4; app/api/directory.php).
 *   GET                     every department (archived ones included, dated)
 *   POST                    create: name, description?, parent_id?, manager_member_id?
 *   PATCH ?id=<department>  rename, re-parent, name the manager, describe
 * Writes: X-Acting-Member; creating needs the super-admin or an administrator of the parent,
 * changing needs an administrator of the department (app_is_admin_of).
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/api/directory.php';

directory_authenticate();
$pdo = db();
$method = directory_method();

if ($method === 'GET') {
    api_json(['schema' => DIRECTORY_SCHEMA, 'departments' => directory_departments($pdo), 'memberships' => directory_memberships($pdo)]);
}
if (!in_array($method, ['POST', 'PATCH'], true)) {
    header('Allow: GET, POST, PATCH');
    api_error('method_not_allowed', 'GET, POST or PATCH.', 405);
}

directory_acting_member($pdo);
$body = directory_body();
$id = $method === 'PATCH' ? (int) ($_GET['id'] ?? 0) : null;
$before = null;
if ($method === 'PATCH') {
    $before = $id > 0 ? find_department($pdo, $id) : null;
    if ($before === null) {
        api_error('not_found', 'Department not found.', 404);
    }
    directory_require($pdo, 'SELECT app_is_admin_of(:d)', ['d' => $id], 'This needs an administrator of that department.');
}

$fields = [
    'name' => array_key_exists('name', $body) ? trim((string) $body['name']) : (string) ($before['name'] ?? ''),
    'description' => array_key_exists('description', $body) ? (trim((string) $body['description']) ?: null) : ($before['description'] ?? null),
    'parent_id' => array_key_exists('parent_id', $body) ? ($body['parent_id'] !== '' && $body['parent_id'] !== null ? (int) $body['parent_id'] : null) : (isset($before['parent_id']) ? (int) $before['parent_id'] : null),
    'manager_member_id' => array_key_exists('manager_member_id', $body) ? ($body['manager_member_id'] !== '' && $body['manager_member_id'] !== null ? (int) $body['manager_member_id'] : null) : (isset($before['manager_member_id']) ? (int) $before['manager_member_id'] : null),
    'home_location_id' => isset($before['home_location_id']) ? (int) $before['home_location_id'] : null,
    'monthly_budget_amount' => $before['monthly_budget_amount'] ?? null,
    'budget_currency' => (string) ($before['budget_currency'] ?? 'USD'),
    'handbook_markdown' => $before['handbook_markdown'] ?? null,
];
if ($fields['name'] === '' || mb_strlen($fields['name']) > 120) {
    api_error('invalid', 'A department needs a name (up to 120 characters).', 422);
}
if ($fields['parent_id'] !== null && find_department($pdo, $fields['parent_id']) === null) {
    api_error('invalid', 'That parent department does not exist.', 422);
}
if ($fields['manager_member_id'] !== null && directory_find_member($pdo, $fields['manager_member_id']) === null) {
    api_error('invalid', 'That manager does not exist.', 422);
}
if ($id !== null && $fields['parent_id'] !== null) {
    if ($fields['parent_id'] === $id) {
        api_error('invalid', 'A department cannot be its own parent.', 422);
    }
    if (department_would_cycle($pdo, $id, $fields['parent_id'])) {
        api_error('invalid', 'That department already reports to this one, directly or further down.', 422);
    }
}
if ($id === null && !is_super_admin()) {
    if ($fields['parent_id'] === null) {
        api_error('forbidden', 'A new department needs a parent you administer.', 403);
    }
    directory_require($pdo, 'SELECT app_is_admin_of(:d)', ['d' => $fields['parent_id']], 'This needs an administrator of the parent department.');
}

try {
    $department = upsert_department($pdo, $id, $fields);
} catch (PDOException $ex) {
    if ($ex->getCode() === '23505') {
        api_error('conflict', 'A department with that name already exists.', 409);
    }
    throw $ex;
}
directory_log($pdo, 'department.save', 'department', (int) $department['id'], [
    'before' => $before === null ? null : ['name' => $before['name'], 'parent_id' => $before['parent_id'], 'manager_member_id' => $before['manager_member_id']],
    'after' => ['name' => $department['name'], 'parent_id' => $department['parent_id'], 'manager_member_id' => $department['manager_member_id']],
]);
api_json(['department' => directory_department_row($department)], $id === null ? 201 : 200);
