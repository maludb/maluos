<?php
declare(strict_types=1);

/**
 * Screen `my-channels` — the channels that reach your personal assistant (db/156): your linked Telegram,
 * phone numbers and addresses, which one replies come back on when you last used none, and your
 * assistant's bot and number. Gate: the person themselves. JSON only (React).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/assistants/assistants.php';

require_insider();
$pdo = db();
$me = (int) current_member_id();
log_screen_view($pdo, 'my-channels');
$assistant = is_agent_member() ? null : my_assistant($pdo, $me);
$st = $pdo->prepare('SELECT id, channel, label, preferred, verified_at, code_expires_at FROM member_channel_identities
                      WHERE member_id = :me AND removed_at IS NULL AND (verified_at IS NOT NULL OR code_expires_at > now())
                      ORDER BY channel, verified_at NULLS LAST');
$st->execute(['me' => $me]);
$endpoints = [];
if ($assistant !== null) {
    $e = $pdo->prepare('SELECT channel, address FROM agent_channel_endpoints WHERE agent_member_id = :a AND active ORDER BY channel');
    $e->execute(['a' => (int) $assistant['id']]);
    $endpoints = $e->fetchAll();
}
respond_screen([
    'assistant' => $assistant !== null ? ['id' => (int) $assistant['id'], 'name' => (string) $assistant['name']] : null,
    'identities' => array_map(static fn (array $i): array => [
        'id' => (int) $i['id'], 'channel' => (string) $i['channel'], 'label' => $i['label'], 'preferred' => (bool) $i['preferred'],
        'verified' => $i['verified_at'] !== null, 'code_expires_at' => json_ts($i['code_expires_at']),
    ], $st->fetchAll()),
    'endpoints' => array_map(static fn (array $e): array => ['channel' => (string) $e['channel'], 'address' => (string) $e['address']], $endpoints),
]);
