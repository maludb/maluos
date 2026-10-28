<?php
declare(strict_types=1);

require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/notifications/queries.php';

require_login();
require_post();
verify_csrf();

$pdo = db();
$me = (int) current_member_id();

if (request_bool('all')) {
    mark_all_notifications_read($pdo, $me);
    log_activity($pdo, 'notification.read', 'notification', null, ['after' => ['all' => true]]);
} else {
    $id = request_integer('notification') ?? request_integer('id');   // manifest param, or the form's
    if ($id === null) { http_response_code(400); exit('Bad request'); }
    mark_notification_read($pdo, $id, $me);
    log_activity($pdo, 'notification.read', 'notification', $id);
}

emit_action_status(true, ['did' => request_bool('all') ? 'Marked every notification read' : 'Marked the notification read', 'unread' => count(unread_notifications($pdo, $me))]);
