<?php
declare(strict_types=1);

/**
 * /api/v1/directory/memberships.php — who is in which department (A4; app/api/directory.php).
 *   GET     every live membership
 *   POST    add (or update): member_id, department_id, is_admin?, is_primary?
 *   DELETE  remove: member_id, department_id (dated, never erased — left_at)
 * Writes: X-Acting-Member, an administrator of that department (app_is_admin_of).
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/api/directory.php';

directory_authenticate();
$pdo = db();
$method = directory_method();

if ($method === 'GET') {
    api_json(['schema' => DIRECTORY_SCHEMA, 'memberships' => directory_memberships($pdo)]);
}
if (!in_array($method, ['POST', 'DELETE'], true)) {
    header('Allow: GET, POST, DELETE');
    api_error('method_not_allowed', 'GET, POST or DELETE.', 405);
}

directory_acting_member($pdo);
$body = directory_body();
$memberId = (int) ($body['member_id'] ?? 0);
$departmentId = (int) ($body['department_id'] ?? 0);
$member = $memberId > 0 ? directory_find_member($pdo, $memberId) : null;
$department = $departmentId > 0 ? find_department($pdo, $departmentId) : null;
if ($member === null || $department === null) {
    api_error('not_found', 'member_id and department_id must name a member and a department.', 404);
}
directory_require($pdo, 'SELECT app_is_admin_of(:d)', ['d' => $departmentId], 'This needs an administrator of that department.');

if ($method === 'POST') {
    $isAdmin = filter_var($body['is_admin'] ?? false, FILTER_VALIDATE_BOOLEAN);
    $isPrimary = filter_var($body['is_primary'] ?? false, FILTER_VALIDATE_BOOLEAN);
    if ($isAdmin && ($member['member_kind'] ?? 'human') !== 'human') {
        api_error('invalid', 'An agent is never a department admin.', 422);
    }
    $row = add_department_member($pdo, $departmentId, $memberId, $isAdmin, $isPrimary);
    directory_log($pdo, 'department.add_member', 'department', $departmentId,
        ['after' => ['member_id' => $memberId, 'is_admin' => $isAdmin, 'is_primary' => $isPrimary]]);
    api_json(['membership' => directory_membership_row($row + ['joined_at' => null, 'left_at' => null])]);
}

$removed = remove_department_member($pdo, $departmentId, $memberId);
if (!$removed) {
    api_error('not_found', 'That person is not in that department.', 404);
}
directory_log($pdo, 'department.remove_member', 'department', $departmentId, ['after' => ['member_id' => $memberId]]);
api_json(['removed' => true, 'member_id' => $memberId, 'department_id' => $departmentId]);
