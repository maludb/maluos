<?php
declare(strict_types=1);

/**
 * The channels worker (db/156; docs/build-specs/assistants-and-messaging.md §6): long-polls every active
 * Telegram endpoint (nothing public), turns each message into an agent message through channel_inbound(),
 * looks for unread mail in every agent mailbox once a minute (the MaluMail webhook's safety net), and sends
 * what agents wrote to people on Telegram, SMS and email (channel_deliver_pending()). One process,
 * run by systemd (docs/deploy/maludb-os-channels.service) as www-data.
 *
 *   php bin/channels_worker.php            # forever
 *   php bin/channels_worker.php --once     # one pass, for a test
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/channels/channels.php';
require_once dirname(__DIR__) . '/app/features/applications/services.php';

$once = in_array('--once', $argv, true);
$say = static fn (string $line) => fwrite(STDOUT, gmdate('Y-m-d H:i:s') . ' ' . $line . "\n");
$lastEmailPoll = 0;

do {
    $pdo = db();
    // Telegram: each endpoint's updates since its offset. Short poll when --once, long poll otherwise.
    foreach ($pdo->query("SELECT id FROM agent_channel_endpoints WHERE channel = 'telegram' AND active ORDER BY id")->fetchAll(PDO::FETCH_COLUMN) as $endpointId) {
        $st = $pdo->prepare('SELECT * FROM agent_channel_endpoints WHERE id = :id');
        $st->execute(['id' => (int) $endpointId]);
        $row = $st->fetch();
        $ep = channel_endpoint($pdo, 'telegram', (int) $row['agent_member_id'], (string) $row['address']);
        if ($ep === null || $ep['secret'] === null) {
            continue;
        }
        try {
            $updates = telegram_api((string) $ep['secret'], 'getUpdates',
                ['offset' => (int) ($ep['config']['offset'] ?? 0), 'timeout' => $once ? 0 : 25, 'allowed_updates' => ['message']], 40);
        } catch (RuntimeException $e) {
            $say('telegram ' . $ep['address'] . ': ' . $e->getMessage());
            sleep(5);
            continue;
        }
        foreach ($updates ?: [] as $u) {
            $offset = (int) $u['update_id'] + 1;
            $msg = $u['message'] ?? null;
            if (is_array($msg) && isset($msg['from']['id'], $msg['chat']['id']) && ($msg['chat']['type'] ?? '') === 'private') {
                $text = (string) ($msg['text'] ?? '');
                $label = isset($msg['from']['username']) ? '@' . $msg['from']['username'] : trim(($msg['from']['first_name'] ?? '') . ' ' . ($msg['from']['last_name'] ?? ''));
                try {
                    [$what, $reply] = channel_inbound($pdo, $ep, (string) $msg['from']['id'], (string) $msg['chat']['id'], $label ?: null,
                        $text !== '' ? $text : '(a message with no text — only text is read)', 'tg:' . $ep['config']['bot_id'] . ':' . $msg['message_id']);
                    if ($reply !== null) {
                        telegram_api((string) $ep['secret'], 'sendMessage', ['chat_id' => $msg['chat']['id'], 'text' => $reply]);
                    }
                    $say('telegram ' . $ep['address'] . ': update ' . $u['update_id'] . ' ' . $what);
                } catch (Throwable $e) {
                    $say('telegram ' . $ep['address'] . ': update ' . $u['update_id'] . ' failed — ' . $e->getMessage());
                }
            }
            // The offset moves past every update, handled or not: one bad message never blocks the rest.
            $pdo->prepare("UPDATE agent_channel_endpoints SET config = jsonb_set(config, '{offset}', to_jsonb(CAST(:o AS bigint))), updated_at = now() WHERE id = :id")
                ->execute(['o' => $offset, 'id' => (int) $ep['id']]);
            $ep['config']['offset'] = $offset;
        }
    }
    // Email: MaluMail's webhook brings mail at once; this look for unread mail is the safety net.
    if ($once || time() - $lastEmailPoll >= EMAIL_POLL_SECONDS) {
        $lastEmailPoll = time();
        foreach ($pdo->query("SELECT agent_member_id, address FROM agent_channel_endpoints WHERE channel = 'email' AND active ORDER BY id")->fetchAll() as $row) {
            $ep = channel_endpoint($pdo, 'email', (int) $row['agent_member_id'], (string) $row['address']);
            if ($ep === null || $ep['secret'] === null) {
                continue;
            }
            try {
                foreach (email_poll($pdo, $ep) as $note) {
                    $say($note);
                }
            } catch (Throwable $e) {
                $say('email ' . $ep['address'] . ': ' . $e->getMessage());
            }
        }
    }
    foreach (channel_deliver_pending($pdo) as $note) {
        $say($note);
    }
    // K6 (db/161): texts applications asked the kernel to send, from the business's notification number.
    foreach (notify_deliver_pending($pdo) as $note) {
        $say($note);
    }
    if (!$once) {
        sleep(2);
    }
} while (!$once);
