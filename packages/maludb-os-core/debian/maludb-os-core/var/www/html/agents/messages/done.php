<?php
declare(strict_types=1);

/** Action `message_done` — log `agent_message.done`. Gate: the message's recipient (an agent in a run, or the person). */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';

require_insider();
require_post();
verify_csrf();

$pdo = db();
$me = (int) current_member_id();
$id = request_integer('message');
$note = mb_substr(trim(request_string('note')), 0, 500) ?: null;
$st = $pdo->prepare('SELECT * FROM agent_messages WHERE id = :id');
$st->execute(['id' => (int) $id]);
$message = $st->fetch();
if ($message === false || (int) $message['to_member_id'] !== $me) {
    emit_action_status(false, ['errors' => ['That message is not in your inbox.']]);
    respond_invalid(['That message is not in your inbox.']);
}
$pdo->prepare("UPDATE agent_messages SET status = 'done', done_at = now(), done_note = :n, read_at = coalesce(read_at, now()) WHERE id = :id")
    ->execute(['n' => $note, 'id' => (int) $id]);
log_activity($pdo, 'agent_message.done', 'agent_message', (int) $id, ['before' => ['status' => $message['status']], 'after' => ['status' => 'done', 'note' => $note]]);
emit_action_status(true, ['did' => 'Marked message ' . (int) $id . ' done']);
