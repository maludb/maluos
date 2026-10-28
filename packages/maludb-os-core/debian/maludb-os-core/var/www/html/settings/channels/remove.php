<?php
declare(strict_types=1);

/** Action `channel_identity_remove` — log `channel_identity.remove`. Gate: the person. That channel stops reaching your assistant at once. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';

require_insider();
require_post();
verify_csrf();
$pdo = db();
$me = (int) current_member_id();
$id = (int) request_integer('identity');
$st = $pdo->prepare('UPDATE member_channel_identities SET removed_at = now(), preferred = false WHERE id = :id AND member_id = :me AND removed_at IS NULL RETURNING channel, label');
$st->execute(['id' => $id, 'me' => $me]);
$row = $st->fetch();
if ($row === false) {
    emit_action_status(false, ['errors' => ['That channel is not yours.']]);
    respond_invalid(['That channel is not yours.']);
}
log_activity($pdo, 'channel_identity.remove', 'member', $me, ['before' => ['channel' => $row['channel'], 'label' => $row['label']]]);
emit_action_status(true, ['did' => 'Removed ' . $row['channel'] . ' ' . $row['label']]);
