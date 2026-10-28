<?php
declare(strict_types=1);

/**
 * Action `agent_chat_send` — one message to one agent on its Chat tab (docs/build-specs/agent-chat.md).
 * Gate: the agent's manager or mod:hr (as agent_run_start); never an agent. Starts one chat run and
 * answers AT ONCE with its ids — the page polls chat-turn.php; nothing here waits for the model.
 * A conversation belongs to the person who started it; the first message opens one.
 * Template-less: a refusal says its own words.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/chat.php';
agents_require_files();

require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    respond_not_found('Agent not found.');
}
agent_require_hr_or_manager($pdo, $agent);
agent_refuse_agent_caller();
$me = (int) current_member_id();

$refuse = static function (string $why): never {
    emit_action_status(false, ['errors' => [$why]]);
    respond_invalid([$why]);
};

$message = trim(request_string('message'));
if ($message === '') {
    $refuse('Say something to ' . $agent['display_name'] . '.');
}
if (mb_strlen($message) > AGENT_CHAT_MESSAGE_MAX) {
    $refuse('Keep a message under ' . AGENT_CHAT_MESSAGE_MAX . ' characters.');
}

$conversationId = request_integer('conversation');
$conversation = null;
$history = [];
if ($conversationId !== null) {
    $conversation = find_agent_conversation($pdo, $conversationId, $me, $id);
    if ($conversation === null) {
        respond_not_found('That conversation is not yours, or is not with this agent.');
    }
    if ($conversation['archived_at'] !== null) {
        $refuse('That conversation is archived — start a new one.');
    }
    // The last turns that ended; a turn still running cannot exist here (the agent would be busy).
    $ended = array_values(array_filter(find_conversation_turns($pdo, (int) $conversation['id']),
        static fn (array $t): bool => $t['status'] !== 'running' && trim((string) $t['chat_utterance']) !== ''));
    $history = array_slice($ended, -AGENT_CHAT_HISTORY_TURNS);
}

$can = agent_chat_availability($pdo, $agent);
if (!$can['can']) {
    $refuse((string) $can['reason']);
}

$me_row = ['id' => $me, 'display_name' => (string) ($_SESSION['member_name'] ?? 'Someone')];
[$run, $error] = start_agent_run($id, build_os_chat_prompt($me_row, $history, $message), 'chat', null, $me);
if ($error !== null) {
    $refuse($error);
}
$runId = (int) $run['run_id'];

if ($conversation === null) {
    $st = $pdo->prepare('INSERT INTO agent_conversations (agent_member_id, member_id, title) VALUES (:a, :p, :t) RETURNING id');
    $st->execute(['a' => $id, 'p' => $me, 't' => chat_title_from($message)]);
    $conversationId = (int) $st->fetchColumn();
} else {
    $conversationId = (int) $conversation['id'];
}
$pdo->prepare('UPDATE agent_runs SET conversation_id = :c, chat_utterance = :u WHERE id = :r')
    ->execute(['c' => $conversationId, 'u' => $message, 'r' => $runId]);

// Ids only, as A6 logs: the words themselves stay in agent_runs.chat_utterance.
log_activity($pdo, 'agent_chat.send', 'member', $id, [
    'agent_run_id' => $runId, 'request_id' => (string) $run['request_id'],
    'after' => ['run_id' => $runId, 'conversation_id' => $conversationId],
]);
$data = ['did' => 'Sent to ' . $agent['display_name'], 'run_id' => $runId, 'conversation_id' => $conversationId];
emit_action_status(true, $data);
respond_saved($data);
