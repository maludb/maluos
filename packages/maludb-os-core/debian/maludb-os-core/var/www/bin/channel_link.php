<?php
declare(strict_types=1);

/**
 * Start linking a person's channel to their assistant (until My settings → Channels is deployed).
 *
 *   php bin/channel_link.php --member 1 --channel telegram          # prints a code to send to the bot
 *   php bin/channel_link.php --member 1 --channel sms --address +15551234567   # texts the code to the number
 *
 * Telegram: the person sends the six-digit code to their assistant's bot; the bot links that account.
 * SMS: the code is texted from the assistant's number; the person texts it back to link the number.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/channels/channels.php';

$o = getopt('', ['member:', 'channel:', 'address:', 'minutes:']);
$minutes = (int) ($o['minutes'] ?? CHANNEL_CODE_MINUTES);
$pdo = db();
$memberId = (int) ($o['member'] ?? 0);
$channel = (string) ($o['channel'] ?? '');
$_SESSION['member_id'] = $memberId;
$st = $pdo->prepare("SELECT p.member_id, m.display_name FROM agent_profiles p JOIN members m ON m.id = p.member_id
                      WHERE p.principal_member_id = :p AND p.status = 'active'");
$st->execute(['p' => $memberId]);
$assistant = $st->fetch();
if ($assistant === false || !in_array($channel, ['telegram', 'sms'], true)) {
    fwrite(STDERR, "The member needs a personal assistant, and the channel is telegram or sms.\n");
    exit(1);
}
$ep = channel_endpoint($pdo, $channel, (int) $assistant['member_id']);
if ($ep === null) {
    fwrite(STDERR, "{$assistant['display_name']} has no {$channel} endpoint (bin/channel_endpoint_set.php).\n");
    exit(1);
}
if ($channel === 'telegram') {
    $code = channel_link_start($pdo, $memberId, 'telegram', null, $minutes);
    echo "Send this code to {$ep['address']} on Telegram within {$minutes} minutes: {$code}\n";
} else {
    $address = preg_replace('/[^\d+]/', '', (string) ($o['address'] ?? ''));
    if (!preg_match('/^\+\d{8,15}$/', (string) $address)) {
        fwrite(STDERR, "Give the number as E.164, like +15551234567.\n");
        exit(1);
    }
    $code = channel_link_start($pdo, $memberId, 'sms', $address);
    twilio_send_sms((string) $ep['config']['account_sid'], (string) $ep['secret'], (string) $ep['address'], $address,
        "Your code to link this number to {$assistant['display_name']}: {$code}. Text it back to this number within 15 minutes.");
    echo "Texted a code to {$address}; text it back to {$ep['address']} to link the number.\n";
}
