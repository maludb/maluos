<?php
declare(strict_types=1);

/** Action `comment_add` — log `record_comment.create`. Gate: whoever can see the record. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/records/queries.php';

require_login();
require_post();
verify_csrf();

$pdo = db();
$entityType = request_string('entity_type');
$entityId = request_integer('entity');
$body = request_string('body');

if (!is_taggable_entity($entityType) || $entityId === null || $body === '') {
    http_response_code(400);
    exit('What are you commenting on, and what does it say?');
}
if (mb_strlen($body) > 5000) {
    http_response_code(400);
    exit('A note is up to 5000 characters.');
}
require_module(entity_module($entityType));
if (!entity_is_visible($pdo, $entityType, $entityId)) {
    http_response_code(404);
    exit('Record not found.');
}

check_approval($pdo, 'comment_add', 'record_comment.create', 'Add a note',
    ['entity_type' => $entityType, 'entity' => $entityId], $entityType, $entityId);

$comment = insert_record_comment($pdo, $entityType, $entityId, $body, (int) current_member_id());
log_activity($pdo, 'record_comment.create', $entityType, $entityId,
    ['after' => ['comment_id' => $comment['comment_id']]]);
emit_action_status(true, ['did' => 'Note added', 'refresh' => 'commentChanged']);
hx_trigger('commentChanged');

echo view('shared/comment-list.php', [
    'comments' => find_record_comments($pdo, $entityType, $entityId),
    'entityType' => $entityType, 'entityId' => $entityId,
    'viewerTz' => current_member()['timezone'] ?? 'UTC',
    'myId' => (int) current_member_id(),
]);
