<?php
declare(strict_types=1);

/** Action `comment_delete` — log `record_comment.delete`. Gate: own (or admin). */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/records/queries.php';

require_login();
require_post();
verify_csrf();

$pdo = db();
$commentId = request_integer('comment');
if ($commentId === null || ($comment = find_record_comment($pdo, $commentId)) === null) {
    http_response_code(404);
    exit('Note not found.');
}
if ((int) $comment['author_member_id'] !== (int) current_member_id() && !is_business_admin()) {
    deny('Only the author can delete a note.');
}

check_approval($pdo, 'comment_delete', 'record_comment.delete', 'Delete a note',
    ['comment' => $commentId], $comment['entity_type'], (int) $comment['entity_id']);

delete_record_comment($pdo, $commentId);
log_activity($pdo, 'record_comment.delete', $comment['entity_type'], (int) $comment['entity_id'],
    ['before' => ['comment_id' => $commentId]]);
emit_action_status(true, ['did' => 'Note deleted', 'refresh' => 'commentChanged']);
hx_trigger('commentChanged');

echo view('shared/comment-list.php', [
    'comments' => find_record_comments($pdo, $comment['entity_type'], (int) $comment['entity_id']),
    'entityType' => $comment['entity_type'], 'entityId' => (int) $comment['entity_id'],
    'viewerTz' => current_member()['timezone'] ?? 'UTC',
    'myId' => (int) current_member_id(),
]);
