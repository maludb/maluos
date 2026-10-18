<?php
declare(strict_types=1);

/**
 * Action `system_event_set_status` — log `system_event.set_status`. Gate: the super-admin, or an admin of
 * the department whose Sysadmin recorded the event (IT). Acknowledge, resolve, mute or reopen one of the
 * Sysadmin's events (db/145), with a note. A resolved event that happens again reopens by itself.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';

require_login();
require_post();
verify_csrf();

$pdo = db();
$refuse = static function (string $m, int $code = 422): never {
    emit_action_status(false, ['errors' => [$m]]);
    if ($code !== 422) { json_error($code === 404 ? 'not_found' : 'forbidden', $m, $code); }
    respond_invalid([$m]);
};
$id = request_integer('event');
$status = request_string('status');
if (!in_array($status, ['open', 'acknowledged', 'resolved', 'muted'], true)) {
    $refuse('Status is open, acknowledged, resolved or muted.');
}
// The view decides who may see — and so who may act on — an event.
$st = $pdo->prepare('SELECT * FROM mcp_system_events WHERE system_event_id = :id');
$st->execute(['id' => $id ?? 0]);
$event = $st->fetch() ?: null;
if ($event === null) { $refuse('That event does not exist, or is not yours to see.', 404); }
if (!is_super_admin() && !is_business_admin()) { $refuse('Only the super-admin or an IT admin acts on system events.', 403); }
$note = mb_substr(trim(request_string('note')), 0, 1000) ?: null;
$pdo->prepare('UPDATE system_events SET status = :s, status_by = :by, status_at = now(), note = COALESCE(:n, note), updated_at = now() WHERE id = :id')
    ->execute(['s' => $status, 'by' => (int) current_member_id(), 'n' => $note, 'id' => (int) $event['system_event_id']]);
log_activity($pdo, 'system_event.set_status', 'system_event', (int) $event['system_event_id'],
    ['before' => ['status' => $event['status']], 'after' => ['status' => $status, 'note' => $note]]);
$did = ucfirst($status === 'open' ? 'reopened' : $status) . ' the event: ' . mb_substr((string) $event['sample'], 0, 80);
emit_action_status(true, ['did' => $did, 'refresh' => 'systemChanged']);
respond_saved(['did' => $did, 'location' => '/ai/system']);
