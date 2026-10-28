<?php
declare(strict_types=1);

/**
 * POST /channels/malumail/mail — MaluMail's new-mail webhook for an agent's mailbox (MaluMail M2). PUBLIC: on
 * the Apache allow-list (docs/deploy/apache-react-cutover.conf), so NOTHING is acted on until the signature
 * (X-MaluMail-Signature, HMAC-SHA256 with the webhook secret of the mailbox named in the body, at most five
 * minutes old) holds. The notice carries headers only; the message itself is read through MaluMail's
 * mailbox MCP (email_inbound()), so a forged notice could at most make us read our own mailbox. Answers 204
 * once verified — whatever became of the message — and 403 otherwise.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/channels/channels.php';

$answer = static function (int $status): never {
    http_response_code($status);
    exit;
};
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    $answer(405);
}
$raw = (string) file_get_contents('php://input', false, null, 0, 65536);
$notice = json_decode($raw, true);
$pdo = db();
$endpoint = is_array($notice) && is_string($notice['address'] ?? null)
    ? channel_endpoint($pdo, 'email', null, strtolower($notice['address'])) : null;
$secretId = (int) ($endpoint['config']['webhook_secret_id'] ?? 0);
$secret = $secretId > 0 ? read_tenant_secret($pdo, $secretId) : null;
if ($endpoint === null || $endpoint['secret'] === null || $secret === null
    || !malumail_signature_valid($secret, (string) ($_SERVER['HTTP_X_MALUMAIL_SIGNATURE'] ?? ''), $raw)) {
    error_log('malumail webhook: refused (no endpoint for the mailbox, no webhook secret, or a bad signature)');
    $answer(403);
}
if (($notice['type'] ?? '') === 'message.new' && ($notice['folder'] ?? '') === 'INBOX' && (int) ($notice['uid'] ?? 0) > 0) {
    try {
        email_inbound($pdo, $endpoint, (int) $notice['uid']);
    } catch (Throwable $e) {
        error_log('malumail webhook: ' . $e->getMessage());       // the worker's poll picks it up
    }
}
$answer(204);
