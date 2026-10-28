<?php
declare(strict_types=1);

/**
 * Action `channel_identity_link` — log `channel_identity.link`. Gate: the person, for themselves.
 * Telegram: answers a six-digit code to send to your assistant's bot. SMS: texts a code to the number you
 * give, from your assistant's number; email: mails a code to the address you give, from your assistant's
 * mailbox — enter either with channel_identity_verify. The code lasts 15 minutes.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/assistants/assistants.php';
require_once dirname(__DIR__, 3) . '/app/features/channels/channels.php';

require_insider();
agent_refuse_agent_caller();
require_post();
verify_csrf();
$pdo = db();
$me = (int) current_member_id();
$refuse = static function (string $why): never { emit_action_status(false, ['errors' => [$why]]); respond_invalid([$why]); };
$channel = request_string('channel');
$assistant = my_assistant($pdo, $me);
if ($assistant === null) {
    $refuse('You have no personal assistant yet — a super-admin assigns one.');
}
if (!in_array($channel, ['telegram', 'sms', 'email'], true)) {
    $refuse('The channel is telegram, sms or email.');
}
$ep = channel_endpoint($pdo, $channel, (int) $assistant['id']);
if ($ep === null) {
    $refuse($assistant['name'] . ' has no ' . $channel . ' yet.');
}
check_approval($pdo, 'channel_identity_link', 'channel_identity.link', 'Link ' . $channel, ['channel' => $channel], 'member', $me);
if ($channel === 'telegram') {
    $code = channel_link_start($pdo, $me, 'telegram');
    log_activity($pdo, 'channel_identity.link', 'member', $me, ['after' => ['channel' => 'telegram']]);
    emit_action_status(true, ['did' => 'Send ' . $code . ' to ' . $ep['address'] . ' on Telegram within 15 minutes.', 'code' => $code, 'bot' => $ep['address']]);
    exit;
}
if ($channel === 'email') {
    $address = strtolower(trim(request_string('address')));
    if (!filter_var($address, FILTER_VALIDATE_EMAIL) || mb_strlen($address) > 254) {
        $refuse('Give an email address, like you@example.com.');
    }
    $code = channel_link_start($pdo, $me, 'email', $address);
    try {
        malumail_mcp((string) $ep['secret'], 'send_message', ['address' => $ep['address'], 'to' => [$address],
            'subject' => 'Your code to link this address to ' . $assistant['name'], 'from_name' => $assistant['name'],
            'text' => 'Your code: ' . $code . "\n\nEnter it on My settings → Channels within 15 minutes. Once linked, mail from "
                . $address . ' to ' . $ep['address'] . ' reaches ' . $assistant['name'] . ".\n\nIf you did not ask for this, ignore this message."]);
    } catch (RuntimeException $e) {
        $refuse('The code could not be mailed: ' . $e->getMessage());
    }
    log_activity($pdo, 'channel_identity.link', 'member', $me, ['after' => ['channel' => 'email', 'label' => $address]]);
    emit_action_status(true, ['did' => 'Mailed a code to ' . $address . ' from ' . $ep['address'] . ' — enter it below.']);
    exit;
}
$address = preg_replace('/[^\d+]/', '', request_string('address'));
if (!preg_match('/^\+\d{8,15}$/', (string) $address)) {
    $refuse('Give the number with its country code, like +15551234567.');
}
$code = channel_link_start($pdo, $me, 'sms', $address);
try {
    twilio_send_sms((string) $ep['config']['account_sid'], (string) $ep['secret'], (string) $ep['address'], $address,
        'Your code to link this number to ' . $assistant['name'] . ': ' . $code . ' (15 minutes).');
} catch (RuntimeException $e) {
    $refuse('The code could not be texted: ' . $e->getMessage());
}
log_activity($pdo, 'channel_identity.link', 'member', $me, ['after' => ['channel' => 'sms', 'label' => $address]]);
emit_action_status(true, ['did' => 'Texted a code to ' . $address . ' — enter it below.']);
