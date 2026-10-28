<?php
declare(strict_types=1);

/**
 * Agent Chat (docs/build-specs/agent-chat.md, db/163): a person talks to ONE agent from its page.
 *
 * A turn is an ordinary agent run with trigger 'chat' — the agent's own grants, the ledger proxy, the
 * approval hook — so nothing here writes accounting or approvals. The person's words are
 * agent_runs.chat_utterance, the agent's are `result`; a conversation (agent_conversations) groups the
 * turns and belongs to one person. This file holds what the OS page and the application endpoint
 * (html/api/v1/agents/chat.php, A6) share: the prompt's history lines, and the rules for who may be
 * chatted with and when.
 */

require_once __DIR__ . '/runs.php';

/** What a person may type in one message on the OS page. */
const AGENT_CHAT_MESSAGE_MAX = 6000;
/** The whole assembled prompt — larger than a duty's, because history rides along (runner enforces no cap). */
const AGENT_CHAT_PROMPT_MAX = 20000;
/** History window (owner, 2026-09-29): the last turns, each cut, the whole capped, oldest dropped first. */
const AGENT_CHAT_HISTORY_TURNS = 10;
const AGENT_CHAT_PERSON_CUT = 1200;
const AGENT_CHAT_AGENT_CUT = 2000;
const AGENT_CHAT_HISTORY_BUDGET = 12000;
/** A title is the first words of the first message. */
const AGENT_CHAT_TITLE_MAX = 60;
/** Harnesses that take a conversational turn: system_one runs named playbooks, not conversation. */
const AGENT_CHAT_HARNESSES = ['hermes', 'claude_agent_sdk'];

/**
 * The lines that carry earlier turns into a prompt, oldest first. Shared by the application's endpoint
 * (3 turns, 600/900 characters) and the OS page (10 turns, 1,200/2,000, budgeted) so their wording
 * cannot drift. A turn with no reply is shown as what it was, so the agent is not misled.
 *
 * @param list<array{chat_utterance: mixed, result: mixed, status?: mixed}> $turns  oldest first
 * @return list<string>
 */
function chat_history_lines(array $turns, int $personCut, int $agentCut, ?int $budget = null): array
{
    $pairs = [];
    foreach ($turns as $turn) {
        $status = (string) ($turn['status'] ?? 'succeeded');
        $said = mb_substr((string) $turn['chat_utterance'], 0, $personCut);
        $reply = match (true) {
            $status === 'succeeded' => mb_substr((string) $turn['result'], 0, $agentCut),
            $status === 'cancelled' => '(the person stopped this turn before you finished)',
            $status === 'failed' => '(this turn failed and you gave no reply)',
            $status === 'awaiting_approval' => trim((string) $turn['result']) !== ''
                ? mb_substr((string) $turn['result'], 0, $agentCut) . ' (then this paused for an approval)'
                : '(this paused for an approval)',
            default => '(no reply yet)',
        };
        $pairs[] = ['Person: ' . $said, 'You: ' . $reply];
    }
    if ($budget !== null) {   // oldest dropped first until the whole fits
        $size = static fn (array $ps): int => array_sum(array_map(static fn (array $p): int => mb_strlen($p[0]) + mb_strlen($p[1]) + 2, $ps));
        while (count($pairs) > 1 && $size($pairs) > $budget) {
            array_shift($pairs);
        }
    }
    return array_merge(...($pairs === [] ? [[]] : $pairs));
}

/**
 * The prompt for one OS chat turn: who is speaking, the standing instruction, what was said before,
 * and the person's message last.
 *
 * @param list<array> $history earlier turns of the conversation, oldest first
 */
function build_os_chat_prompt(array $person, array $history, string $message): string
{
    $lines = [
        'A person is talking to you directly in the Business OS, on your own Chat tab. '
        . 'Answer them plainly. When the message asks for work, do it with your tools, then say what you did; '
        . 'say plainly what you could not do and what paused for approval.',
        'Person: ' . (string) $person['display_name'] . ' (member ' . (int) $person['id'] . '), a super-admin of this business.',
    ];
    $earlier = chat_history_lines($history, AGENT_CHAT_PERSON_CUT, AGENT_CHAT_AGENT_CUT, AGENT_CHAT_HISTORY_BUDGET);
    if ($earlier !== []) {
        $lines[] = 'Earlier in this conversation (oldest first):';
        array_push($lines, ...$earlier);
    }
    $lines[] = 'Their message: ' . $message;
    return mb_substr(implode("\n", $lines), 0, AGENT_CHAT_PROMPT_MAX);
}

/**
 * Why this agent can never (right now) take a typed turn, in the page's own words — or null when it can.
 * Independent of what it is doing this minute, so the Chat tab can be the default for exactly the agents
 * that are chat-capable and stay put while one is briefly busy.
 */
function agent_chat_unavailable_reason(array $agent): ?string
{
    $name = (string) ($agent['display_name'] ?? 'This agent');
    if (($agent['agent_kind'] ?? '') === 'voice') {
        return $name . ' is a voice agent — it answers calls, not typed messages.';
    }
    if (($agent['status'] ?? '') !== 'active') {
        return $name . ' is ' . ($agent['status'] ?? 'not active') . ', so cannot be chatted with.';
    }
    if (($agent['current_config_version_id'] ?? null) === null) {
        return $name . ' has no active configuration version yet — activate one on the Job tab.';
    }
    if (!in_array((string) ($agent['harness'] ?? ''), AGENT_CHAT_HARNESSES, true)) {
        return $name . ' runs playbooks ("' . ($agent['harness'] ?? 'unknown') . '"), not conversation — use its Duties.';
    }
    return null;
}

/**
 * Whether this agent can take a chat turn now, and if not, in whose words. One run at a time per agent
 * (the runner refuses a second): a busy agent is refused with what it is doing (owner, 2026-09-29).
 *
 * @return array{can: bool, reason: ?string, busy_run_id: ?int}
 */
function agent_chat_availability(PDO $pdo, array $agent): array
{
    $never = agent_chat_unavailable_reason($agent);
    if ($never !== null) {
        return ['can' => false, 'reason' => $never, 'busy_run_id' => null];
    }
    $st = $pdo->prepare("SELECT id, trigger FROM agent_runs WHERE agent_member_id = :a AND status = 'running' ORDER BY id DESC LIMIT 1");
    $st->execute(['a' => (int) $agent['agent_member_id']]);
    if (($busy = $st->fetch()) !== false) {
        $what = $busy['trigger'] === 'chat' ? 'answering a chat' : ('on a ' . str_replace('_', ' ', (string) $busy['trigger']) . ' run');
        return ['can' => false, 'busy_run_id' => (int) $busy['id'],
                'reason' => ($agent['display_name'] ?? 'This agent') . ' is busy — ' . $what . ' (run #' . (int) $busy['id'] . '). Try again when it finishes.'];
    }
    return ['can' => true, 'reason' => null, 'busy_run_id' => null];
}

/** A conversation of this person's, or null — a conversation is private to its person. */
function find_agent_conversation(PDO $pdo, int $conversationId, int $personId, ?int $agentId = null): ?array
{
    $st = $pdo->prepare('SELECT id, agent_member_id, member_id, title, created_at, archived_at
                           FROM agent_conversations
                          WHERE id = :id AND member_id = :p' . ($agentId !== null ? ' AND agent_member_id = :a' : ''));
    $params = ['id' => $conversationId, 'p' => $personId] + ($agentId !== null ? ['a' => $agentId] : []);
    $st->execute($params);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** This person's conversations with this agent, newest first (archived only when asked for). */
function find_agent_conversations(PDO $pdo, int $agentId, int $personId, bool $archived = false): array
{
    $st = $pdo->prepare('SELECT c.id, c.title, c.created_at, c.archived_at,
                                (SELECT max(r.id) FROM agent_runs r WHERE r.conversation_id = c.id) AS last_run_id,
                                (SELECT count(*) FROM agent_runs r WHERE r.conversation_id = c.id) AS turns,
                                (SELECT max(coalesce(r.finished_at, r.started_at)) FROM agent_runs r WHERE r.conversation_id = c.id) AS last_at
                           FROM agent_conversations c
                          WHERE c.agent_member_id = :a AND c.member_id = :p AND (c.archived_at IS NOT NULL) = :arch
                          ORDER BY coalesce((SELECT max(r.id) FROM agent_runs r WHERE r.conversation_id = c.id), 0) DESC, c.id DESC
                          LIMIT 50');
    $st->bindValue('a', $agentId, PDO::PARAM_INT);
    $st->bindValue('p', $personId, PDO::PARAM_INT);
    $st->bindValue('arch', $archived, PDO::PARAM_BOOL);
    $st->execute();
    return $st->fetchAll();
}

/**
 * The turns of a conversation, oldest first. A turn carries what the page shows: the words, the state,
 * and the cost. Tools come from agent_run_events when the page asks for one turn in flight.
 */
function find_conversation_turns(PDO $pdo, int $conversationId, ?int $limit = null): array
{
    $st = $pdo->prepare('SELECT id, status, chat_utterance, result, error, approval_request_id, cost, currency,
                                started_at, finished_at, model_id, requested_by
                           FROM agent_runs WHERE conversation_id = :c ORDER BY id'
        . ($limit !== null ? ' LIMIT ' . (int) $limit : ''));
    $st->execute(['c' => $conversationId]);
    return $st->fetchAll();
}

/** A title from the first words of a message: one line, cut at a word. */
function chat_title_from(string $message): string
{
    $line = trim((string) preg_replace('/\s+/u', ' ', $message));
    if (mb_strlen($line) <= AGENT_CHAT_TITLE_MAX) {
        return $line;
    }
    $cut = mb_substr($line, 0, AGENT_CHAT_TITLE_MAX);
    $space = mb_strrpos($cut, ' ');
    return rtrim($space !== false && $space > 20 ? mb_substr($cut, 0, $space) : $cut, " ,.;:-") . '…';
}
