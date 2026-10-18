<?php
declare(strict_types=1);

/** Action `tag_remove` — log `tag.remove`. Gate: the module that owns the entity. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/records/queries.php';

require_login();
require_post();
verify_csrf();

$pdo = db();
$entityType = request_string('entity_type');
$entityId = request_integer('entity');
$tagId = request_integer('tag');

if (!is_taggable_entity($entityType) || $entityId === null || $tagId === null) {
    http_response_code(400);
    exit('Which tag, on what?');
}
require_module(entity_module($entityType));
if (!entity_is_visible($pdo, $entityType, $entityId)) {
    http_response_code(404);
    exit('Record not found.');
}

check_approval($pdo, 'tag_remove', 'tag.remove', 'Remove a tag',
    ['entity_type' => $entityType, 'entity' => $entityId, 'tag' => $tagId], $entityType, $entityId);

remove_tagging($pdo, $entityType, $entityId, $tagId);
log_activity($pdo, 'tag.remove', $entityType, $entityId, ['before' => ['tag_id' => $tagId]]);
emit_action_status(true, ['did' => 'Tag removed', 'refresh' => 'taggingChanged']);
hx_trigger('taggingChanged');

echo view('shared/tags.php', [
    'entityType' => $entityType, 'entityId' => $entityId,
    'taggings' => find_taggings($pdo, $entityType, $entityId), 'canEdit' => true,
]);
