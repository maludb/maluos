<?php
declare(strict_types=1);

/**
 * Action `channel_identity_verify` — log `channel_identity.verify`. Gate: the person. The code texted to your
 * number (channel sms, the default) or mailed to your address (channel email) links it.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/channels/channels.php';

require_insider();
require_post();
verify_csrf();
$pdo = db();
$me = (int) current_member_id();
$channel = request_string('channel') === 'email' ? 'email' : 'sms';
$code = preg_replace('/\D/', '', request_string('code'));
$pending = strlen((string) $code) === 6 ? channel_link_by_code($pdo, $channel, (string) $code) : null;
if ($pending === null || (int) $pending['member_id'] !== $me) {
    emit_action_status(false, ['errors' => ['That code is wrong or has expired — ask for a new one.']]);
    respond_invalid(['That code is wrong or has expired — ask for a new one.']);
}
channel_link_verify($pdo, $pending, (string) $pending['address'], (string) $pending['address'], (string) $pending['address']);
emit_action_status(true, ['did' => 'Linked ' . $pending['address'] . ' — ' . ($channel === 'email' ? 'mail' : 'texts')
    . ' from it now reach your assistant.']);
