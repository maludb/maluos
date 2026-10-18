<?php
declare(strict_types=1);

/** Action `tag_add` — log `tag.add`. Gate: the module that owns the entity. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/records/queries.php';

require_login();
require_post();
verify_csrf();

$pdo = db();
$entityType = request_string('entity_type');
$entityId = request_integer('entity');
$tagName = request_string('tag');

if (!is_taggable_entity($entityType) || $entityId === null || $tagName === '') {
    http_response_code(400);
    exit('What should be tagged, and with what?');
}
if (mb_strlen($tagName) > 40) {
    http_response_code(400);
    exit('A tag is up to 40 characters.');
}
// The gate is the entity's own module: tagging a contact needs the contacts module, and a
// member who cannot see the record cannot tag it either.
require_module(entity_module($entityType));
if (!entity_is_visible($pdo, $entityType, $entityId)) {
    http_response_code(404);
    exit('Record not found.');
}

check_approval($pdo, 'tag_add', 'tag.add', 'Tag with ' . $tagName,
    ['entity_type' => $entityType, 'entity' => $entityId, 'tag' => $tagName], $entityType, $entityId);

$tag = add_tagging($pdo, $entityType, $entityId, $tagName, (int) current_member_id());
log_activity($pdo, 'tag.add', $entityType, $entityId, ['after' => ['tag' => $tag['name']]]);
emit_action_status(true, ['did' => 'Tagged with ' . $tag['name'], 'refresh' => 'taggingChanged']);
hx_trigger('taggingChanged');

echo view('shared/tags.php', [
    'entityType' => $entityType, 'entityId' => $entityId,
    'taggings' => find_taggings($pdo, $entityType, $entityId), 'canEdit' => true,
]);
