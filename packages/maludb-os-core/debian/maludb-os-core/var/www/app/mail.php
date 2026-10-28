<?php
declare(strict_types=1);

/**
 * Send one email via MaluMail (api.malumail.com). Returns the decoded response.
 * Throws RuntimeException on transport errors and non-2xx responses.
 * In dev with no API key configured, logs the message instead of sending.
 */
function malumail_send(array $mail): array
{
    $key = env('MALUMAIL_API_KEY', '');
    if ($key === '' && !app_is_prod()) {
        error_log('[dev mail] to=' . json_encode($mail['to'] ?? '') . ' subject=' . ($mail['subject'] ?? ''));
        return ['status' => 'sent', 'accepted' => (array) ($mail['to'] ?? []), 'rejected' => [], 'dev_noop' => true];
    }

    $ch = curl_init('https://api.malumail.com/v1/send');
    curl_setopt_array($ch, [
        CURLOPT_POST           => true,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 30,
        CURLOPT_HTTPHEADER     => [
            'Authorization: Bearer ' . $key,
            'Content-Type: application/json',
        ],
        CURLOPT_POSTFIELDS     => json_encode($mail, JSON_THROW_ON_ERROR),
    ]);
    $body   = curl_exec($ch);
    $status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $errno  = curl_errno($ch);
    curl_close($ch);

    if ($errno !== 0 || $body === false) {
        throw new RuntimeException('MaluMail transport error.');
    }
    $decoded = json_decode((string) $body, true);
    if ($status !== 200) {
        throw new RuntimeException("MaluMail send failed ({$status}): " . ($decoded['error'] ?? 'unknown'));
    }
    return $decoded;
}

/** Send a rendered email (text + html templates under app/views/emails/) and log it. */
function send_email(string $to, string $subject, string $template, array $data = []): void
{
    $html = view("emails/{$template}.html.php", $data);
    $text = view("emails/{$template}.text.php", $data);
    try {
        $result = malumail_send([
            'from'      => (string) env('MAIL_FROM', 'noreply@example.com'),
            'from_name' => (string) env('MAIL_FROM_NAME', env('APP_NAME', 'App')),
            'to'        => $to,
            'subject'   => $subject,
            'html'      => $html,
            'text'      => $text,
        ]);
        log_activity(db(), 'notification.sent', 'email', null, [
            'after' => ['to' => $to, 'subject' => $subject, 'rejected' => $result['rejected'] ?? []],
        ]);
    } catch (Throwable $e) {
        error_log('send_email failed: ' . $e->getMessage());
    }
}
