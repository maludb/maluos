<?php
declare(strict_types=1);

/**
 * Action `invitation_send` — invite someone by email. Gate: admin; the super-admin role can only
 * be granted by a super-admin; a dept-admin invites only into a department they administer (the
 * same rule mcp_business_invitations applies to what they may then see). Approval: `send`.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/invitations/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';

require_business_admin();
require_post();
verify_csrf();

$pdo = db();
$email = normalize_email(request_string('email'));
$role = request_string('business_role', 'user');
$departmentId = request_integer('department');
$message = trim(request_string('message'));

$errors = [];
if ($email === '' || filter_var($email, FILTER_VALIDATE_EMAIL) === false) {
    $errors[] = 'Enter a valid email address.';
} elseif (find_member_by_email($pdo, $email) !== null) {
    $errors[] = 'That email already belongs to someone here.';
}
if (!in_array($role, INVITABLE_BUSINESS_ROLES, true)) {
    $errors[] = 'Choose what they will be: user, department admin or super-admin.';
}
if (mb_strlen($message) > 2000) {
    $errors[] = 'Keep the message under 2,000 characters.';
}
$department = $departmentId !== null ? find_department($pdo, $departmentId) : null;
if ($departmentId !== null && $department === null) {
    $errors[] = 'That department does not exist.';
}
if ($role === 'dept_admin' && $departmentId === null) {
    $errors[] = 'A department admin needs a department to administer.';
}
if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);   // no template to carry the words: say them
}

if ($role === 'super_admin' && !is_super_admin()) {
    deny('Only a super-admin can invite another super-admin.');
}
if (!is_super_admin()) {
    if ($departmentId === null) {
        deny('Choose one of your departments — you invite people into the departments you administer.');
    }
    require_admin_for_department($pdo, $departmentId);
}

check_approval($pdo, 'invitation_send', 'invitation.send',
    'Invite ' . $email . ' as ' . $role . ($department !== null ? ' into ' . $department['name'] : ''),
    ['email' => $email, 'business_role' => $role, 'department' => $departmentId, 'message' => $message],
    'invitation', null);

$result = insert_business_invitation($pdo, $email, $role, $departmentId, (int) current_member_id(), $message);
if (!$result['ok']) {
    emit_action_status(false, ['errors' => [$result['error']]]);
    respond_invalid([$result['error']]);   // no template to carry the words: say them
}
$invitation = $result['invitation'];

log_activity($pdo, 'invitation.send', 'invitation', (int) $invitation['id'], [
    'after' => ['email' => $email, 'business_role' => $role, 'department_id' => $departmentId],
]);
send_email($email, 'You are invited to ' . business_name($pdo), 'invite', [
    'url'     => app_url('/register?token=' . $result['raw_token']),
    'inviter' => current_member()['display_name'] ?? 'An administrator',
    'message' => $message,
    'role'    => $role,
]);

emit_action_status(true, ['did' => 'Invitation sent to ' . $email, 'refresh' => 'invitationsChanged']);
header('HX-Push-Url: /team/invitations');
