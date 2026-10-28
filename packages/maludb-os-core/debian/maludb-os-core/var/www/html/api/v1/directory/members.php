<?php
declare(strict_types=1);

/**
 * /api/v1/directory/members.php — the directory API (A4; app/api/directory.php).
 *   GET                 every member with their live departments (the mirror's full refresh)
 *   POST                invite a human: an invitation goes out; the member exists once they register
 *   PATCH ?id=<member>  name, job title, phone, timezone, external flag, status (active|suspended),
 *                       role user <-> dept_admin — never a super-admin, never an agent
 * Writes need X-Acting-Member and the application's directory.writes; the acting person's own
 * rights decide (the people rule: app_can_admin_member).
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/api/directory.php';
require_once dirname(__DIR__, 4) . '/app/features/invitations/queries.php';

directory_authenticate();
$pdo = db();

switch (directory_method()) {
    case 'GET':
        api_json(['schema' => DIRECTORY_SCHEMA, 'members' => directory_members($pdo)]);

    case 'POST':
        $acting = directory_acting_member($pdo);
        $body = directory_body();
        $email = normalize_email((string) ($body['email'] ?? ''));
        $role = (string) ($body['business_role'] ?? 'user');
        $departmentId = isset($body['department_id']) && $body['department_id'] !== '' ? (int) $body['department_id'] : null;
        $message = trim((string) ($body['message'] ?? ''));
        $errors = [];
        if ($email === '' || filter_var($email, FILTER_VALIDATE_EMAIL) === false) {
            $errors[] = 'Enter a valid email address.';
        } elseif (find_member_by_email($pdo, $email) !== null) {
            $errors[] = 'That email already belongs to someone here.';
        }
        if (!in_array($role, ['user', 'dept_admin'], true)) {
            $errors[] = 'business_role is user or dept_admin; a super-admin is invited from the operating system.';
        }
        $department = $departmentId !== null ? find_department($pdo, $departmentId) : null;
        if ($departmentId !== null && $department === null) {
            $errors[] = 'That department does not exist.';
        }
        if ($role === 'dept_admin' && $departmentId === null) {
            $errors[] = 'A department admin needs a department to administer.';
        }
        if (mb_strlen($message) > 2000) {
            $errors[] = 'Keep the message under 2,000 characters.';
        }
        if ($errors !== []) {
            api_error('invalid', $errors[0], 422);
        }
        if (!is_super_admin()) {
            if ($departmentId === null) {
                api_error('forbidden', 'Choose one of your departments — you invite people into the departments you administer.', 403);
            }
            directory_require($pdo, 'SELECT app_is_admin_of(:d)', ['d' => $departmentId], 'This needs an administrator of that department.');
        }
        $result = insert_business_invitation($pdo, $email, $role, $departmentId, (int) $acting['id'], $message === '' ? null : $message);
        if (!$result['ok']) {
            api_error('conflict', (string) $result['error'], 409);
        }
        $invitation = $result['invitation'];
        directory_log($pdo, 'invitation.send', 'invitation', (int) $invitation['id'],
            ['after' => ['email' => $email, 'business_role' => $role, 'department_id' => $departmentId]]);
        send_email($email, 'You are invited to ' . business_name($pdo), 'invite', [
            'url' => app_url('/register?token=' . $result['raw_token']),
            'inviter' => $acting['display_name'] ?? 'An administrator',
            'message' => $message, 'role' => $role,
        ]);
        api_json(['status' => 'invited', 'invitation_id' => (int) $invitation['id'], 'email' => $email,
            'expires_at' => json_ts($invitation['expires_at'] ?? null)], 202);

    case 'PATCH':
        $acting = directory_acting_member($pdo);
        $id = (int) ($_GET['id'] ?? 0);
        $current = $id > 0 ? directory_find_member($pdo, $id) : null;
        if ($current === null) {
            api_error('not_found', 'Member not found.', 404);
        }
        if (($current['member_kind'] ?? 'human') !== 'human') {
            api_error('forbidden', 'Agents are the operating system\'s to change.', 403);
        }
        if (($current['business_role'] ?? '') === 'super_admin') {
            api_error('forbidden', 'A super-admin is changed only from the operating system.', 403);
        }
        directory_require($pdo, 'SELECT app_can_admin_member(:m)', ['m' => $id], 'You do not administer this person.');
        $body = directory_body();
        $set = [];
        $args = ['id' => $id];
        $after = [];
        if (array_key_exists('display_name', $body)) {
            $v = trim((string) $body['display_name']);
            if ($v === '' || mb_strlen($v) > 120) { api_error('invalid', 'A name is 1 to 120 characters.', 422); }
            $set[] = 'display_name = :display_name'; $args['display_name'] = $v; $after['display_name'] = $v;
        }
        foreach (['job_title' => 120, 'phone' => 60] as $key => $max) {
            if (array_key_exists($key, $body)) {
                $v = trim((string) $body[$key]);
                if (mb_strlen($v) > $max) { api_error('invalid', ucfirst(str_replace('_', ' ', $key)) . " is up to {$max} characters.", 422); }
                $set[] = "{$key} = :{$key}"; $args[$key] = $v === '' ? null : $v; $after[$key] = $v === '' ? null : $v;
            }
        }
        if (array_key_exists('timezone', $body)) {
            $v = (string) $body['timezone'];
            if (!in_array($v, timezone_identifiers_list(), true)) { api_error('invalid', 'That is not a time zone.', 422); }
            $set[] = 'timezone = :timezone'; $args['timezone'] = $v; $after['timezone'] = $v;
        }
        if (array_key_exists('is_external', $body)) {
            $v = filter_var($body['is_external'], FILTER_VALIDATE_BOOLEAN);
            $set[] = 'is_external = :is_external'; $args['is_external'] = $v ? 't' : 'f'; $after['is_external'] = $v;
        }
        if (array_key_exists('status', $body)) {
            $v = (string) $body['status'];
            if (!in_array($v, ['active', 'suspended'], true)) { api_error('invalid', 'status is active or suspended; offboarding is done from the operating system.', 422); }
            $set[] = 'status = :status'; $args['status'] = $v; $after['status'] = $v;
        }
        if (array_key_exists('business_role', $body)) {
            $v = (string) $body['business_role'];
            if (!in_array($v, ['user', 'dept_admin'], true)) { api_error('invalid', 'business_role is user or dept_admin.', 422); }
            $set[] = 'business_role = :business_role'; $args['business_role'] = $v; $after['business_role'] = $v;
        }
        if ($set === []) {
            api_error('invalid', 'Nothing to change: send display_name, job_title, phone, timezone, is_external, status or business_role.', 422);
        }
        $pdo->prepare('UPDATE members SET ' . implode(', ', $set) . ', updated_at = now() WHERE id = :id')->execute($args);
        $before = array_intersect_key($current, $after);
        directory_log($pdo, 'member.update', 'member', $id, ['before' => $before, 'after' => $after]);
        $fresh = directory_find_member($pdo, $id);
        api_json(['member' => directory_members_one($pdo, $fresh)]);

    default:
        header('Allow: GET, POST, PATCH');
        api_error('method_not_allowed', 'GET, POST or PATCH.', 405);
}

/** One member with their live departments, as the list shows them. */
function directory_members_one(PDO $pdo, array $m): array
{
    $st = $pdo->prepare('SELECT dm.department_id AS id, d.name, dm.is_admin, dm.is_primary FROM department_members dm JOIN departments d ON d.id = dm.department_id WHERE dm.member_id = :m AND dm.left_at IS NULL ORDER BY dm.is_primary DESC, d.name');
    $st->execute(['m' => (int) $m['id']]);
    $departments = array_map(static fn (array $r): array => ['id' => (int) $r['id'], 'name' => (string) $r['name'], 'is_admin' => !empty($r['is_admin']), 'is_primary' => !empty($r['is_primary'])], $st->fetchAll());
    return directory_member_row($m, $departments);
}
