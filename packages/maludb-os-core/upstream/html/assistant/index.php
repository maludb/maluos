<?php
declare(strict_types=1);

/**
 * Screen `my-assistant` — a person and their personal assistant (db/154–156): the conversation across every
 * channel, oldest first, and what the assistant handed on — to whom, in which department, why, and what
 * came back. Opening it marks the assistant's messages read. Writing goes through message_send (to the
 * assistant). Gate: the person themselves (any insider). JSON only (React).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/assistants/assistants.php';

require_insider();
$pdo = db();
$me = (int) current_member_id();
log_screen_view($pdo, 'my-assistant');
$assistant = is_agent_member() ? null : my_assistant($pdo, $me);
if ($assistant === null) {
    respond_screen(['assistant' => null, 'messages' => [], 'handoffs' => []]);
}
$pdo->prepare("UPDATE agent_messages SET status = 'read', read_at = now() WHERE to_member_id = :me AND from_member_id = :a AND status = 'unread'")
    ->execute(['me' => $me, 'a' => (int) $assistant['id']]);
$channels = $pdo->prepare('SELECT channel, label, preferred FROM member_channel_identities WHERE member_id = :me AND verified_at IS NOT NULL AND removed_at IS NULL ORDER BY channel');
$channels->execute(['me' => $me]);
respond_screen([
    'assistant' => ['id' => (int) $assistant['id'], 'name' => (string) $assistant['name']],
    'channels' => array_map(static fn (array $c): array => ['channel' => (string) $c['channel'], 'label' => (string) $c['label'], 'preferred' => (bool) $c['preferred']], $channels->fetchAll()),
    'messages' => array_map(static fn (array $m): array => [
        'id' => (int) $m['id'], 'thread_id' => (int) $m['thread_id'], 'thread_subject' => (string) $m['thread_subject'],
        'mine' => (int) $m['from_member_id'] === $me, 'kind' => (string) $m['kind'], 'priority' => (string) $m['priority'],
        'subject' => (string) $m['subject'], 'body' => (string) $m['body'], 'channel' => (string) $m['channel'],
        'delivery_channel' => $m['delivery_channel'], 'delivered' => $m['delivered_at'] !== null,
        'delivery_error' => $m['delivery_error'], 'created_at' => json_ts($m['created_at']),
    ], assistant_conversation($pdo, $me, (int) $assistant['id'])),
    'handoffs' => array_map(static fn (array $h): array => [
        'run_id' => (int) $h['run_id'], 'agent_id' => (int) $h['agent_member_id'], 'agent_name' => (string) $h['agent_name'],
        'department' => $h['department_name'], 'reason' => $h['delegation_reason'], 'status' => (string) $h['status'],
        'instructions' => (string) $h['instructions'], 'result' => (string) $h['result'],
        'started_at' => json_ts($h['started_at']), 'finished_at' => json_ts($h['finished_at']),
    ], assistant_handoffs($pdo, (int) $assistant['id'])),
]);
