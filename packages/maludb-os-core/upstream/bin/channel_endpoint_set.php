<?php
declare(strict_types=1);

/**
 * Give an agent a channel endpoint (db/156): a Telegram bot, a Twilio number or a MaluMail mailbox. The credential goes
 * straight into a tenant secret (encrypted, rotation keeps the same reference) — it is read from an env
 * file by KEY and never printed.
 *
 *   php bin/channel_endpoint_set.php --agent 34 --channel telegram --env-file /home/maludb/.env --token-key '@my_bot'
 *   php bin/channel_endpoint_set.php --agent 34 --channel sms --env-file /home/maludb/.env \
 *        --sid-key TWILIO_ACCOUNT_SID --token-key TWILIO_AUTH_TOKEN --number-key TWILIO_PHONE
 *
 *   php bin/channel_endpoint_set.php --agent 34 --channel email --env-file /home/maludb/.env --token-key MALUMAIL_API_KEY \
 *        --address seamus@subello.com [--webhook-url https://app.subello.com/channels/malumail/mail]
 *
 * Telegram: the token is checked with getMe, and the bot's @username becomes the endpoint's address.
 * Email: the MaluMail API key (with "Mailbox MCP" on) is the secret; the mailbox is created through MaluMail's
 * MCP when it does not exist (its password is thrown away — the OS never needs one); with --webhook-url the
 * mailbox's new-mail webhook is set and its signing secret (rotated on every run) stored as a second tenant
 * secret, referenced from the endpoint's config. Without it the worker's once-a-minute poll alone brings mail.
 * SMS: the number must be E.164 (+15551234567); the account SID is kept in the endpoint's config (not a
 * secret), the auth token as the secret. Running it again rotates the secret in place.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/channels/channels.php';

$o = getopt('', ['agent:', 'channel:', 'env-file:', 'token-key:', 'sid-key:', 'number-key:', 'by:', 'address:', 'webhook-url:']);
$pdo = db();
$agentId = (int) ($o['agent'] ?? 0);
$channel = (string) ($o['channel'] ?? '');
$by = (int) ($pdo->query("SELECT id FROM members WHERE business_role = 'super_admin' AND member_kind = 'human' AND status = 'active' ORDER BY id LIMIT 1")->fetchColumn());
$_SESSION['member_id'] = $by;
if ($agentId < 1 || !in_array($channel, ['telegram', 'sms', 'email'], true) || empty($o['env-file']) || empty($o['token-key'])) {
    fwrite(STDERR, "Usage: see the header of this file.\n");
    exit(1);
}

/** One value from an env file by its exact key — the file is never sourced, and nothing is printed. */
$env = static function (string $file, string $key): string {
    foreach (file($file, FILE_IGNORE_NEW_LINES) ?: [] as $line) {
        $at = strpos($line, '=');
        if ($at !== false && substr($line, 0, $at) === $key) {
            return trim(substr($line, $at + 1), " \t\"'");
        }
    }
    fwrite(STDERR, "No {$key} in the env file.\n");
    exit(1);
};
$token = $env((string) $o['env-file'], (string) $o['token-key']);
$agent = $pdo->prepare('SELECT m.display_name FROM members m JOIN agent_profiles p ON p.member_id = m.id WHERE m.id = :id');
$agent->execute(['id' => $agentId]);
$agentName = $agent->fetchColumn();
if ($agentName === false) {
    fwrite(STDERR, "No agent {$agentId}.\n");
    exit(1);
}

if ($channel === 'telegram') {
    try {
        $me = telegram_api($token, 'getMe');
    } catch (RuntimeException $e) {
        fwrite(STDERR, 'The token did not work: ' . $e->getMessage() . "\n");
        exit(1);
    }
    $address = '@' . (string) $me['username'];
    $config = ['bot_id' => (int) $me['id'], 'offset' => 0];
} elseif ($channel === 'email') {
    $address = strtolower(trim((string) ($o['address'] ?? '')));
    if (!filter_var($address, FILTER_VALIDATE_EMAIL)) {
        fwrite(STDERR, "--address must be the mailbox, like seamus@subello.com.\n");
        exit(1);
    }
    [$local, $domain] = explode('@', $address, 2);
    try {
        $boxes = malumail_mcp($token, 'list_mailboxes', ['domain' => $domain]);
        if (!in_array($address, array_column($boxes['mailboxes'] ?? [], 'address'), true)) {
            malumail_mcp($token, 'create_mailbox', ['domain' => $domain, 'local_part' => $local, 'quota_gib' => 2]);
            echo "Created the mailbox {$address} (2 GiB).\n";
        }
        $config = [];
        if (!empty($o['webhook-url'])) {
            $hook = malumail_mcp($token, 'set_mailbox_webhook', ['address' => $address, 'url' => (string) $o['webhook-url'], 'active' => true, 'rotate_secret' => true]);
            if (empty($hook['secret'])) {
                throw new RuntimeException('MaluMail set the webhook but returned no secret.');
            }
            $config['webhook_secret_id'] = store_tenant_secret($pdo, 'channel.email.webhook.' . $address, 'channel', 'malumail', (string) $hook['secret'], $by);
            $config['webhook_url'] = (string) $o['webhook-url'];
            echo "New-mail webhook set to {$o['webhook-url']}.\n";
        }
    } catch (RuntimeException $e) {
        fwrite(STDERR, $e->getMessage() . "\n");
        exit(1);
    }
} else {
    $sid = $env((string) $o['env-file'], (string) ($o['sid-key'] ?? 'TWILIO_ACCOUNT_SID'));
    $address = preg_replace('/[^\d+]/', '', $env((string) $o['env-file'], (string) ($o['number-key'] ?? 'TWILIO_PHONE')));
    if (!preg_match('/^\+\d{8,15}$/', (string) $address)) {
        fwrite(STDERR, "The number must be E.164, like +15551234567.\n");
        exit(1);
    }
    $config = ['account_sid' => $sid];
}

$secretName = 'channel.' . $channel . '.' . ltrim((string) $address, '@+');
$secretName = $channel === 'email' ? 'channel.email.malumail-api-key' : $secretName;   // one account key serves every mailbox
$secretId = store_tenant_secret($pdo, $secretName, 'channel', ['telegram' => 'telegram', 'sms' => 'twilio', 'email' => 'malumail'][$channel], $token, $by);
$st = $pdo->prepare('SELECT id FROM agent_channel_endpoints WHERE channel = :c AND address = :a AND active');
$st->execute(['c' => $channel, 'a' => $address]);
$existing = $st->fetchColumn();
if ($existing !== false) {
    $pdo->prepare('UPDATE agent_channel_endpoints SET agent_member_id = :m, secret_id = :s,
                          config = config || CAST(:cfg AS jsonb), updated_at = now() WHERE id = :id')
        ->execute(['m' => $agentId, 's' => $secretId, 'cfg' => json_encode($config), 'id' => (int) $existing]);
} else {
    $pdo->prepare('INSERT INTO agent_channel_endpoints (agent_member_id, channel, address, secret_id, config, created_by)
                   VALUES (:m, :c, :a, :s, CAST(:cfg AS jsonb), :by)')
        ->execute(['m' => $agentId, 'c' => $channel, 'a' => $address, 's' => $secretId, 'cfg' => json_encode($config), 'by' => $by]);
}
log_activity($pdo, 'agent_channel.set', 'member', $agentId, ['source' => 'cron',
    'after' => ['channel' => $channel, 'address' => $address, 'secret' => $secretName]]);
echo "{$agentName}: {$channel} endpoint {$address} (credential stored as tenant secret {$secretName}).\n";
