<?php
declare(strict_types=1);

/**
 * Action `invitation_resend` — a fresh link and a fresh expiry for a pending invitation. The old
 * link stops working. Gate: admin, and the invitation must be one the caller may manage.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/invitations/queries.php';

require_business_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('invitation');
if ($id === null || ($invitation = find_pending_business_invitation($pdo, $id)) === null) {
    http_response_code(404);
    exit('Invitation not found.');
}

check_approval($pdo, 'invitation_resend', 'invitation.send',
    'Resend the invitation to ' . $invitation['email'], ['invitation' => $id], 'invitation', $id);

$raw = resend_invitation($pdo, $id);
if ($raw === null) {
    emit_action_status(false, ['errors' => ['That invitation was accepted or revoked a moment ago.']]);
    respond_invalid(['That invitation was accepted or revoked a moment ago.']);   // no template to carry the words: say them
}

log_activity($pdo, 'invitation.send', 'invitation', $id, ['after' => ['email' => $invitation['email'], 'resent' => true]]);
send_email((string) $invitation['email'], 'Your invitation to ' . business_name($pdo), 'invite', [
    'url'     => app_url('/register?token=' . $raw),
    'inviter' => current_member()['display_name'] ?? 'An administrator',
    'message' => '',
    'role'    => (string) $invitation['business_role_granted'],
]);

emit_action_status(true, ['did' => 'Invitation resent to ' . $invitation['email'], 'refresh' => 'invitationsChanged']);
header('HX-Push-Url: /team/invitations');
