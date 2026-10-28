<?php
declare(strict_types=1);

/**
 * Action `invitation_revoke` — the link stops working at once. Gate: admin, and the invitation
 * must be one the caller may manage. Destructive (the manifest asks for confirmation).
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

check_approval($pdo, 'invitation_revoke', 'invitation.revoke',
    'Revoke the invitation to ' . $invitation['email'], ['invitation' => $id], 'invitation', $id);

if (!revoke_invitation($pdo, $id)) {
    emit_action_status(false, ['errors' => ['That invitation was accepted or revoked a moment ago.']]);
    respond_invalid(['That invitation was accepted or revoked a moment ago.']);   // no template to carry the words: say them
}

log_activity($pdo, 'invitation.revoke', 'invitation', $id, ['after' => ['email' => $invitation['email']]]);
emit_action_status(true, ['did' => 'Revoked the invitation to ' . $invitation['email'], 'refresh' => 'invitationsChanged']);
header('HX-Push-Url: /team/invitations');
