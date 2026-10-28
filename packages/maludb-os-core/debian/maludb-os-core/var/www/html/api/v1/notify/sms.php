<?php
declare(strict_types=1);

/**
 * K6 — an application texts a member through the kernel (db/161; docs/build-specs/kernel-app-services.md).
 *
 *   POST /api/v1/notify/sms.php   {member_id, text, reference?}  → 202 {notification: {id, status: queued}}
 *   GET  /api/v1/notify/sms.php?id=<notification>                 → {notification: {id, status, sent_at, error}}
 *
 * Bearer = the application's token (internal port). The kernel sends from the business's notification number to
 * the member's verified phone; the application never sees either. Refusals: 422 invalid | not_held |
 * no_verified_phone | opted_out | rate_limited, 503 no_sender.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/api/directory.php';
require_once dirname(__DIR__, 4) . '/app/features/applications/services.php';

directory_authenticate();
$pdo = db();
$app = directory_application();

if (directory_method() === 'GET') {
    $id = (int) ($_GET['id'] ?? 0);
    $n = $id > 0 ? notify_status($pdo, $app, $id) : null;
    if ($n === null) {
        api_error('not_found', 'No such text from this application.', 404);
    }
    api_json(['notification' => $n]);
}
if (directory_method() !== 'POST') {
    header('Allow: GET, POST');
    api_error('method_not_allowed', 'GET or POST.', 405);
}
$body = directory_body();
$memberId = (int) ($body['member_id'] ?? 0);
if ($memberId <= 0 || !is_string($body['text'] ?? null)) {
    api_error('invalid', 'member_id and text are required.', 422);
}
[$status, $payload] = notify_sms_queue($pdo, $app, $memberId, (string) $body['text'],
    isset($body['reference']) ? (string) $body['reference'] : null);
if ($status >= 400) {
    api_error($payload['code'], $payload['message'], $status);
}
api_json($payload, $status);
