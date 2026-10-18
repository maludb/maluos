<?php
declare(strict_types=1);

/** Action `agent_chat_rename` — give one of the person's own conversations a title (docs/build-specs/agent-chat.md). */
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

$title = trim((string) preg_replace('/\s+/u', ' ', request_string('title')));
if ($title === '' || mb_strlen($title) > 120) {
    emit_action_status(false, ['errors' => ['A title is 1 to 120 characters.']]);
    respond_invalid(['A title is 1 to 120 characters.']);
}
$pdo->prepare('UPDATE agent_conversations SET title = :t WHERE id = :id')->execute(['t' => $title, 'id' => $id]);

log_activity($pdo, 'agent_chat.rename', 'member', (int) $conversation['agent_member_id'], ['after' => ['conversation_id' => $id]]);
$data = ['did' => 'Renamed the conversation', 'conversation_id' => $id];
emit_action_status(true, $data);
respond_saved($data);
