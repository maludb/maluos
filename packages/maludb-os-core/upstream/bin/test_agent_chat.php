<?php
declare(strict_types=1);

/**
 * Proof of Agent Chat's rules — docs/build-specs/agent-chat.md, db/163. Nothing is sent to a model and
 * nothing is kept: the database part runs in a transaction that is rolled back.
 *
 *   php bin/test_agent_chat.php
 *
 * Covers: the shared history lines (A6's wording unchanged), the OS prompt (order, window, budget, the
 * verbatim person's words last), titles, who can be chatted with, and that a conversation is private to its person.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/agents/render.php';
require_once dirname(__DIR__) . '/app/features/agents/chat.php';
agents_require_files();

$pdo = db();
$fails = 0;
$ok = static function (bool $c, string $label) use (&$fails): void { if (!$c) { $fails++; } echo ($c ? '  ok   ' : '  FAIL ') . $label . "\n"; };

echo "History lines\n";
$turns = [['chat_utterance' => str_repeat('a', 700), 'result' => str_repeat('b', 1000)], ['chat_utterance' => 'hi', 'result' => 'hello']];
$a6 = [];
foreach ($turns as $t) { $a6[] = 'Person: ' . mb_substr($t['chat_utterance'], 0, 600); $a6[] = 'You: ' . mb_substr($t['result'], 0, 900); }
$ok(chat_history_lines($turns, 600, 900) === $a6, "the application endpoint's wording is byte-for-byte unchanged");
$mixed = chat_history_lines([['chat_utterance' => 'q1', 'result' => '', 'status' => 'cancelled'], ['chat_utterance' => 'q2', 'result' => '', 'status' => 'failed'], ['chat_utterance' => 'q3', 'result' => 'r3', 'status' => 'succeeded']], 100, 100);
$ok(str_contains($mixed[1], 'stopped') && str_contains($mixed[3], 'failed') && $mixed[5] === 'You: r3', 'a stopped or failed turn is shown as what it was');
$big = [];
for ($i = 1; $i <= 10; $i++) { $big[] = ['chat_utterance' => "q$i " . str_repeat('x', 1100), 'result' => "r$i " . str_repeat('y', 1900)]; }
$fit = chat_history_lines($big, AGENT_CHAT_PERSON_CUT, AGENT_CHAT_AGENT_CUT, AGENT_CHAT_HISTORY_BUDGET);
$ok(mb_strlen(implode("\n", $fit)) <= AGENT_CHAT_HISTORY_BUDGET + 40, 'the budget holds (' . mb_strlen(implode("\n", $fit)) . ' characters)');
$ok(str_starts_with(end($fit), 'You: r10') && !str_contains(implode("\n", $fit), 'q1 '), 'the oldest turns go first, the newest stays');

echo "OS prompt\n";
$person = ['id' => 7, 'display_name' => 'Ada Admin'];
$p = build_os_chat_prompt($person, array_slice($big, -2), 'Please summarise September spend.');
$ok(str_contains($p, 'Ada Admin (member 7)') && str_contains($p, 'Earlier in this conversation'), 'says who is speaking and carries the history');
$ok(str_ends_with($p, 'Their message: Please summarise September spend.'), "the person's words come last, verbatim");
$ok(!str_contains(build_os_chat_prompt($person, [], 'hello'), 'Earlier in this conversation'), 'a first message has no history block');
$ok(mb_strlen(build_os_chat_prompt($person, $big, str_repeat('m', AGENT_CHAT_MESSAGE_MAX))) <= AGENT_CHAT_PROMPT_MAX, 'the whole prompt stays under its cap');

echo "Titles\n";
$ok(chat_title_from("  How much did\nwe spend?  ") === 'How much did we spend?', 'whitespace collapses');
$t = chat_title_from(str_repeat('word ', 30));
$ok(mb_strlen($t) <= AGENT_CHAT_TITLE_MAX + 1 && str_ends_with($t, '…'), 'a long first message is cut at a word');

echo "Who can be chatted with\n";
$base = ['display_name' => 'Test', 'agent_kind' => 'subagent', 'status' => 'active', 'current_config_version_id' => 5, 'harness' => 'claude_agent_sdk', 'agent_member_id' => 0];
$ok(agent_chat_unavailable_reason($base) === null, 'an active claude_agent_sdk agent can');
$ok(agent_chat_unavailable_reason(['harness' => 'hermes'] + $base) === null, 'a hermes agent can');
$ok(str_contains((string) agent_chat_unavailable_reason(['harness' => 'system_one'] + $base), 'playbooks'), 'a system_one agent cannot — it runs playbooks');
$ok(str_contains((string) agent_chat_unavailable_reason(['agent_kind' => 'voice'] + $base), 'voice'), 'a voice agent cannot');
$ok(str_contains((string) agent_chat_unavailable_reason(['status' => 'suspended'] + $base), 'suspended'), 'a suspended agent cannot');
$ok(str_contains((string) agent_chat_unavailable_reason(['current_config_version_id' => null] + $base), 'no active configuration'), 'an agent with no live version cannot');

echo "Conversations are private (rolled back)\n";
$people = $pdo->query("SELECT id FROM members WHERE member_kind = 'human' AND status = 'active' ORDER BY id LIMIT 2")->fetchAll(PDO::FETCH_COLUMN);
$agentId = (int) $pdo->query("SELECT member_id FROM agent_profiles ORDER BY member_id LIMIT 1")->fetchColumn();
if (count($people) < 2 || $agentId === 0) {
    $ok(false, 'needs two active people and one agent');
} else {
    [$me, $other] = array_map('intval', $people);
    $pdo->beginTransaction();
    try {
        $st = $pdo->prepare("INSERT INTO agent_conversations (agent_member_id, member_id, title) VALUES (:a, :p, 'SMOKE chat') RETURNING id");
        $st->execute(['a' => $agentId, 'p' => $me]);
        $cid = (int) $st->fetchColumn();
        $ok(find_agent_conversation($pdo, $cid, $me) !== null, 'the owner finds it');
        $ok(find_agent_conversation($pdo, $cid, $other) === null, "another person's lookup finds nothing");
        $ok(find_agent_conversation($pdo, $cid, $me, $agentId + 999999) === null, 'nor the same person under the wrong agent');
        $ok(count(array_filter(find_agent_conversations($pdo, $agentId, $me), static fn (array $c): bool => (int) $c['id'] === $cid)) === 1, 'it is on the owner\'s list');
        $ok(find_agent_conversations($pdo, $agentId, $other) === [] || !in_array($cid, array_map(static fn (array $c): int => (int) $c['id'], find_agent_conversations($pdo, $agentId, $other)), true), "and not on another's list");
        // The MCP view answers only the caller's own.
        $_SESSION['member_id'] = $me; db_apply_context($pdo);
        $mine = (int) $pdo->query("SELECT count(*) FROM mcp_agent_conversations WHERE conversation_id = $cid")->fetchColumn();
        $_SESSION['member_id'] = $other; db_apply_context($pdo);
        $theirs = (int) $pdo->query("SELECT count(*) FROM mcp_agent_conversations WHERE conversation_id = $cid")->fetchColumn();
        $ok($mine === 1 && $theirs === 0, 'mcp_agent_conversations shows it to its person alone');
    } finally {
        $pdo->rollBack();
    }
}

echo $fails === 0 ? "\nAll passed.\n" : "\n$fails FAILED.\n";
exit($fails === 0 ? 0 : 1);
