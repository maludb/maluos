<?php
declare(strict_types=1);

/** Action `channel_identity_prefer` — log `channel_identity.prefer`. Gate: the person. Where replies go when you last wrote from none. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';

require_insider();
require_post();
verify_csrf();
$pdo = db();
$me = (int) current_member_id();
$id = (int) request_integer('identity');
$pdo->beginTransaction();
$pdo->prepare('UPDATE member_channel_identities SET preferred = false WHERE member_id = :me AND preferred')->execute(['me' => $me]);
$st = $pdo->prepare('UPDATE member_channel_identities SET preferred = true WHERE id = :id AND member_id = :me AND verified_at IS NOT NULL AND removed_at IS NULL RETURNING channel, label');
$st->execute(['id' => $id, 'me' => $me]);
$row = $st->fetch();
if ($row === false) {
    $pdo->rollBack();
    emit_action_status(false, ['errors' => ['That channel is not one of your linked channels.']]);
    respond_invalid(['That channel is not one of your linked channels.']);
}
$pdo->commit();
log_activity($pdo, 'channel_identity.prefer', 'member', $me, ['after' => ['channel' => $row['channel'], 'label' => $row['label']]]);
emit_action_status(true, ['did' => 'Replies now come by ' . $row['channel'] . ' (' . $row['label'] . ') when you have not written from elsewhere']);
