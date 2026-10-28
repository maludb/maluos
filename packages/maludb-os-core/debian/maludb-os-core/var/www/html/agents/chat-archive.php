<?php
declare(strict_types=1);

/**
 * Action `agent_chat_archive` — hide one of the person's own conversations (archive=1, the default) or
 * bring it back (archive=0). Nothing is deleted: its runs are audit records (docs/build-specs/agent-chat.md).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/chat.php';
agents_require_files();

require_post();
verify_csrf();

$pdo = db();
$id = request_integer('conversation');
$conversation = $id !== null ? find_agent_conversation($pdo, $id, (int) current_member_id()) : null;
if ($conversation === null || ($agent = find_agent($pdo, (int) $conversation['agent_member_id'])) === null) {
    respond_not_found('That conversation is not yours.');
}
agent_require_hr_or_manager($pdo, $agent);
agent_refuse_agent_caller();

$archive = request_string('archive', '1') !== '0';
$st = $pdo->prepare('UPDATE agent_conversations SET archived_at = ' . ($archive ? 'coalesce(archived_at, now())' : 'NULL') . ' WHERE id = :id');
$st->execute(['id' => $id]);

log_activity($pdo, 'agent_chat.archive', 'member', (int) $conversation['agent_member_id'], [
    'after' => ['conversation_id' => $id, 'archived' => $archive],
]);
$data = ['did' => ($archive ? 'Archived' : 'Restored') . ' the conversation with ' . $agent['display_name'], 'conversation_id' => $id];
emit_action_status(true, $data);
respond_saved($data);
