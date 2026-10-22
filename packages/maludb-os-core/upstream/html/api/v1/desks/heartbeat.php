<?php
declare(strict_types=1);

/**
 * POST /api/v1/desks/heartbeat — presence and facts from an enrolled desk (Bearer desk token). Not logged
 * to activity: every few minutes, and last_seen_at is the record. 410 once the desk is retired.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/desks.php';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
    api_error('method_not_allowed', 'Only POST is supported.', 405);
}
$ctx = desk_authenticate();
$body = desk_body();
$presence = (string) ($body['presence'] ?? 'online');
if (!in_array($presence, ['online', 'offline'], true)) {
    api_error('invalid', 'presence is online or offline.', 400);
}
$pdo = db();
desk_heartbeat($pdo, (int) $ctx['desk']['id'], $presence, $body);
api_json(desk_answer($pdo, desk_row($pdo, (int) $ctx['desk']['id']), $ctx['member']));
