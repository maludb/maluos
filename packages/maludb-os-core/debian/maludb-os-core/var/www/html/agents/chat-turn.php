<?php
declare(strict_types=1);

/**
 * `agent_chat_turn` (read) — the state of ONE chat turn, polled by the Chat tab while the agent works
 * (docs/build-specs/agent-chat.md). GET ?run=<id>&after=<event seq>. Only the person the conversation
 * belongs to: the run must be a chat turn of one of THEIR conversations. Answers the words, the state,
 * the tool events after the cursor, and whether an approval holds it.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/chat.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/present.php';
agents_require_files();

require_login();
agent_refuse_agent_caller();
$pdo = db();
$runId = request_integer('run');
$run = $runId !== null ? find_agent_run($pdo, $runId) : null;
if ($run === null || $run['conversation_id'] === null
    || find_agent_conversation($pdo, (int) $run['conversation_id'], (int) current_member_id()) === null) {
    respond_not_found('No chat turn by that id.');
}
$after = max(0, (int) request_integer('after'));

$st = $pdo->prepare("SELECT seq, event, tool_name, status, duration_ms, occurred_at FROM agent_run_events
                      WHERE agent_run_id = :r AND seq > :s AND event IN ('pre_tool_call', 'post_tool_call') ORDER BY seq LIMIT 200");
$st->execute(['r' => (int) $run['id'], 's' => $after]);
$events = array_map(static fn (array $e): array => [
    'seq' => (int) $e['seq'], 'event' => (string) $e['event'],
    'tool' => preg_replace('/^mcp__[a-z0-9_]+?__/', '', (string) $e['tool_name']) ?: (string) $e['tool_name'],
    'status' => $e['status'] !== null ? (string) $e['status'] : null,
    'duration_ms' => $e['duration_ms'] !== null ? (int) $e['duration_ms'] : null,
], $st->fetchAll());

json_response(present_chat_turn($run) + ['events' => $events]);
