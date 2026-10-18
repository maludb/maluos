<?php
declare(strict_types=1);

/**
 * POST /channels/twilio/sms — Twilio's webhook for a text to an agent's number (db/156). PUBLIC: it is on
 * the Apache allow-list (docs/deploy/apache-react-cutover.conf), so NOTHING is read until Twilio's
 * signature over CHANNELS_TWILIO_SMS_URL (the exact public URL set on the number in Twilio's console) and
 * the POST fields holds, with the auth token of the number the text was sent TO. Then it is an ordinary
 * inbound message: a code links the sender's number; a verified person reaches their own assistant;
 * anything else is dropped and logged, and answered with nothing. The answer is always empty TwiML — a
 * reply, if any, goes out later through the worker like every other.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/channels/channels.php';

$empty = static function (int $status = 200): never {
    http_response_code($status);
    header('Content-Type: text/xml');
    echo '<?xml version="1.0" encoding="UTF-8"?><Response></Response>';
    exit;
};
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    $empty(405);
}
$url = (string) env('CHANNELS_TWILIO_SMS_URL', '');
$to = preg_replace('/[^\d+]/', '', (string) ($_POST['To'] ?? ''));
$pdo = db();
$endpoint = $url !== '' && $to !== '' ? channel_endpoint($pdo, 'sms', null, $to) : null;
if ($endpoint === null || $endpoint['secret'] === null
    || !twilio_signature_valid((string) $endpoint['secret'], $url, $_POST, (string) ($_SERVER['HTTP_X_TWILIO_SIGNATURE'] ?? ''))) {
    error_log('twilio sms webhook: refused (no endpoint for the number, no configured URL, or a bad signature)');
    $empty(403);
}
$from = preg_replace('/[^\d+]/', '', (string) ($_POST['From'] ?? ''));
try {
    [$what, $reply] = channel_inbound($pdo, $endpoint, $from, $from, $from, (string) ($_POST['Body'] ?? ''),
        'twilio:' . (string) ($_POST['MessageSid'] ?? bin2hex(random_bytes(8))));
    if ($reply !== null) {
        twilio_send_sms((string) $endpoint['config']['account_sid'], (string) $endpoint['secret'], (string) $endpoint['address'], $from, $reply);
    }
} catch (Throwable $e) {
    error_log('twilio sms webhook: ' . $e->getMessage());
}
$empty();
