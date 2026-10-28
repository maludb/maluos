<?php
declare(strict_types=1);
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/settings/queries.php';
require_login(); require_post(); verify_csrf();
$pdo = db(); $me = (int) current_member_id();
update_notifications($pdo, $me, request_bool('notify_reply'), request_bool('notify_event'), request_bool('notify_exam'), request_bool('notify_digest'));
log_activity($pdo, 'member.update', 'member', $me, ['after' => ['notifications' => true]]);
emit_action_status(true, ['did' => 'Preferences saved']);
echo settings_section_html($pdo, $me, 'notifications', ['notice' => 'Preferences saved.']);
