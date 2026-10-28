<?php
declare(strict_types=1);

/**
 * Action `message_send` — log `agent_message.send`. Gate: an agent inside one of its runs, or a person
 * writing to their own assistant (db/155).
 *
 * Messages go along the orchestrator tree (db/154): to your orchestrator, to an agent on your roster, or to
 * a lead beside you under the same orchestrator; a person writes only to their assistant, and only an
 * assistant writes to its person. app_message_send() holds every rule (the tree, 30 an hour between two
 * members, the thread's hop limit) and says which one refused. A new message wakes an agent recipient
 * (the runner's message loop). Born after the cut-over: no template, so a refusal says its own words.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';

require_insider();
require_post();
verify_csrf();

$pdo = db();
$me = (int) current_member_id();
$runId = current_agent_run_id();
$refuse = static function (array $errors, int $status = 422): never {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);
};
if (is_agent_member() && $runId === null) {
    $refuse(['An agent sends messages from inside one of its runs.'], 403);
}

$to = trim(request_string('to'));
$kind = request_string('kind', 'fyi') ?: 'fyi';
$subject = trim(request_string('subject'));
$body = trim((string) ($_POST['body'] ?? ''));
$thread = request_integer('thread');
$priority = request_string('priority', 'normal') ?: 'normal';
$errors = [];
if ($to === '') { $errors[] = 'Say who the message is for (to).'; }
if (!in_array($kind, ['request', 'result', 'question', 'decision_needed', 'fyi', 'reply'], true)) {
    $errors[] = 'kind is request, result, question, decision_needed, fyi or reply.';
}
if ($subject === '' && $thread === null) { $errors[] = 'A new thread needs a subject.'; }
if ($body === '') { $errors[] = 'The message needs a body.'; }
if (mb_strlen($body) > 20000) { $errors[] = 'Keep a message under 20,000 characters — attach a record instead.'; }
if (!in_array($priority, ['normal', 'urgent'], true)) { $errors[] = 'priority is normal or urgent.'; }
if ($errors !== []) {
    $refuse($errors);
}

// The recipient, by id or by name among active members.
$st = $pdo->prepare("SELECT id, display_name, member_kind FROM members
                      WHERE status = 'active' AND (id::text = :t OR lower(display_name) = lower(:t) OR lower(email::text) = lower(:t))
                      ORDER BY id LIMIT 2");
$st->execute(['t' => $to]);
$found = $st->fetchAll();
if (count($found) !== 1) {
    $refuse([$found === [] ? 'Nobody active is called "' . $to . '".' : '"' . $to . '" names more than one member — use the id.']);
}
$recipient = $found[0];
if ($subject === '' && $thread !== null) {
    $st = $pdo->prepare('SELECT subject FROM agent_message_threads WHERE id = :t');
    $st->execute(['t' => $thread]);
    $subject = (string) ($st->fetchColumn() ?: 'Re:');
}

check_approval($pdo, 'message_send', 'agent_message.send', 'Message ' . $recipient['display_name'] . ': ' . $subject,
    ['to' => (int) $recipient['id'], 'kind' => $kind, 'thread' => $thread], 'member', (int) $recipient['id']);

try {
    $st = $pdo->prepare('SELECT app_message_send(:f, :t, :k, :s, :b, :th, :p, :c, NULL, NULL, :run)');
    $st->execute(['f' => $me, 't' => (int) $recipient['id'], 'k' => $kind, 's' => $subject, 'b' => $body,
                  'th' => $thread, 'p' => $priority, 'c' => is_agent_member() ? 'internal' : 'web', 'run' => $runId]);
    $messageId = (int) $st->fetchColumn();
} catch (PDOException $ex) {
    $why = preg_match('/ERROR:\s*(.+?)(\n|$)/', $ex->getMessage(), $m) && $ex->getCode() === 'P0001' ? trim($m[1]) : 'The message could not be sent.';
    $refuse([$why]);
}
$st = $pdo->prepare('SELECT thread_id FROM agent_messages WHERE id = :id');
$st->execute(['id' => $messageId]);
$threadId = (int) $st->fetchColumn();
log_activity($pdo, 'agent_message.send', 'agent_message', $messageId, [
    'after' => ['to_member_id' => (int) $recipient['id'], 'kind' => $kind, 'thread_id' => $threadId, 'subject' => $subject],
]);
emit_action_status(true, ['did' => 'Sent to ' . $recipient['display_name'] . ' (thread ' . $threadId . ')'
    . ($recipient['member_kind'] === 'agent' ? ' — it will be woken to read it.' : '.'),
    'record_id' => $messageId, 'thread_id' => $threadId]);
