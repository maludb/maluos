<?php
declare(strict_types=1);

/**
 * POST /api/v1/desks/leave — the desk retires itself (Bearer desk token): status retired, the token revoked,
 * logged as the owner. Residents and anything else that points at the desk are not in the way: the desk
 * is gone from under them, as a machine that was wiped is.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/estate/desks.php';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
    api_error('method_not_allowed', 'Only POST is supported.', 405);
}
$ctx = desk_authenticate();
$pdo = db();
$id = (int) $ctx['desk']['id'];
desk_retire($pdo, $id);
log_activity($pdo, 'desk.leave', 'location', $id, ['source' => 'desk',
    'before' => ['status' => 'active', 'name' => $ctx['desk']['name']], 'after' => ['status' => 'retired']]);
api_json(['ok' => true, 'surface' => DESK_SURFACE, 'desk' => ['id' => $id, 'name' => (string) $ctx['desk']['name'], 'status' => 'retired']]);
