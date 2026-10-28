<?php
declare(strict_types=1);

/**
 * The chat endpoint (A6, 2026-09-22 — docs/build-specs/kernel-chat-endpoint.md).
 *
 *   POST /api/v1/agents/chat.php?agent=expert|<member id>    body {utterance, screen?, context?, conversation_id?, wait?}
 *   GET  /api/v1/agents/chat.php?run=<run id>                 the state of a chat run of this application
 *
 * An application's command bar posts what the person said; the kernel runs ONE turn of the
 * application's shipped agent — its expert, or another agent that holds access to it — as an
 * agent run (trigger 'chat'): the agent's own grants, every model call through the ledger proxy,
 * approvals paused in the kernel's queue, the person as requester, the application on the run and
 * on its ledger rows. The application never calls a model and holds no model key. The answer is
 * the reply, the tool calls the run made, and whether something paused for approval; a run that
 * outlasts `wait` answers 202 and is fetched again with GET.
 *
 * Bearer = the application's token; X-Acting-Member = the person (a live grant on the application).
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/api/directory.php';
require_once dirname(__DIR__, 4) . '/app/features/agents/runs.php';
require_once dirname(__DIR__, 4) . '/app/features/agents/chat.php';

const CHAT_WAIT_DEFAULT = 60;
const CHAT_WAIT_MAX = 110;
const CHAT_HISTORY_TURNS = 3;
const CHAT_UTTERANCE_MAX = 4000;

directory_authenticate();
$pdo = db();
$app = directory_application();
$acting = application_acting_member($pdo);
$method = directory_method();

/** The answer for one chat run, as the application renders it. */
function chat_answer(PDO $pdo, array $run): array
{
    $st = $pdo->prepare("SELECT tool_name, status, duration_ms, detail FROM agent_run_events
                          WHERE agent_run_id = :r AND event = 'post_tool_call' ORDER BY seq");
    $st->execute(['r' => (int) $run['id']]);
    $actions = [];
    foreach ($st->fetchAll() as $e) {
        $detail = is_string($e['detail']) ? (json_decode($e['detail'], true) ?: []) : (array) $e['detail'];
        $tool = (string) $e['tool_name'];
        $actions[] = ['tool' => preg_replace('/^mcp__[a-z0-9_]+?__/', '', $tool) ?: $tool, 'status' => (string) ($e['status'] ?? ''),
            'duration_ms' => isset($e['duration_ms']) ? (int) $e['duration_ms'] : null,
            'record_id' => isset($detail['record_id']) ? (int) $detail['record_id'] : null];
    }
    $status = (string) $run['status'];
    return [
        'run_id' => (int) $run['id'],
        'request_id' => (string) $run['request_id'],
        'status' => $status,
        'finished' => $status !== 'running',
        'reply' => $status === 'succeeded' || $status === 'awaiting_approval' ? ($run['result'] ?? null) : null,
        'error' => $status === 'failed' ? ($run['error'] ?? 'The run failed.') : null,
        'approval_request_id' => isset($run['approval_request_id']) ? (int) $run['approval_request_id'] : null,
        'actions' => $actions,
        'navigate' => null,
        'conversation_id' => $run['conversation_key'] ?? null,
        'cost' => $run['cost'] !== null ? (string) $run['cost'] : null,
        'currency' => $run['currency'] ?? null,
    ];
}

/** Once a run has ended, the application is stamped on every ledger row it produced. */
function chat_stamp_ledger(PDO $pdo, int $runId, int $applicationId): void
{
    $pdo->prepare('UPDATE prompt_ledger SET application_id = :a WHERE agent_run_id = :r AND application_id IS NULL')
        ->execute(['a' => $applicationId, 'r' => $runId]);
}

if ($method === 'GET') {
    $runId = (int) ($_GET['run'] ?? 0);
    $run = $runId > 0 ? find_agent_run($pdo, $runId) : null;
    if ($run === null || (int) ($run['application_id'] ?? 0) !== $app['id'] || $run['trigger'] !== 'chat') {
        api_error('not_found', 'No chat run by that id for this application.', 404);
    }
    if ($run['status'] !== 'running') {
        chat_stamp_ledger($pdo, (int) $run['id'], $app['id']);
    }
    api_json(chat_answer($pdo, $run), $run['status'] === 'running' ? 202 : 200);
}
if ($method !== 'POST') {
    header('Allow: GET, POST');
    api_error('method_not_allowed', 'GET or POST.', 405);
}

$body = directory_body();
$utterance = trim((string) ($body['utterance'] ?? ''));
if ($utterance === '') {
    api_error('invalid', 'Say something: utterance is empty.', 422);
}
if (mb_strlen($utterance) > CHAT_UTTERANCE_MAX) {
    api_error('invalid', 'Keep an utterance under ' . CHAT_UTTERANCE_MAX . ' characters.', 422);
}
$screen = trim((string) ($body['screen'] ?? ''));
$context = is_array($body['context'] ?? null) ? $body['context'] : [];
$conversation = trim((string) ($body['conversation_id'] ?? ''));
if ($conversation !== '' && !preg_match('/^[A-Za-z0-9_.:-]{1,120}$/', $conversation)) {
    api_error('invalid', 'conversation_id is up to 120 letters, digits, dots, dashes, colons or underscores.', 422);
}
$wait = max(0, min(CHAT_WAIT_MAX, (int) ($body['wait'] ?? CHAT_WAIT_DEFAULT)));

// Which agent: the application's expert, or an agent that holds access to the application.
$which = trim((string) ($_GET['agent'] ?? $body['agent'] ?? 'expert'));
if ($which === 'expert') {
    $agentId = (int) ($pdo->query('SELECT sme_agent_member_id FROM applications WHERE id = ' . $app['id'])->fetchColumn() ?: 0);
    if ($agentId <= 0) {
        api_error('not_found', 'This application has no expert yet — a super-admin names one on its Expertise tab.', 404);
    }
} elseif (ctype_digit($which)) {
    $agentId = (int) $which;
} else {
    api_error('invalid', 'agent is "expert" or an agent\'s member id.', 422);
}
$st = $pdo->prepare("SELECT m.id, m.display_name, m.status, p.status AS agent_status
                       FROM members m JOIN agent_profiles p ON p.member_id = m.id
                      WHERE m.id = :id AND m.member_kind = 'agent'");
$st->execute(['id' => $agentId]);
$agent = $st->fetch() ?: null;
if ($agent === null) {
    api_error('not_found', 'No agent by that id.', 404);
}
if ($agent['agent_status'] !== 'active' || $agent['status'] !== 'active') {
    api_error('conflict', $agent['display_name'] . ' is not active.', 409);
}
$st = $pdo->prepare("SELECT (SELECT sme_agent_member_id FROM applications WHERE id = :a) = :m
                         OR EXISTS (SELECT 1 FROM application_access ac
                                     WHERE ac.application_id = :a2 AND ac.revoked_at IS NULL AND (ac.expires_at IS NULL OR ac.expires_at > now())
                                       AND (ac.member_id = :m2 OR ac.department_id IN (SELECT dm.department_id FROM department_members dm WHERE dm.member_id = :m3 AND dm.left_at IS NULL)))");
$st->execute(['a' => $app['id'], 'm' => $agentId, 'a2' => $app['id'], 'm2' => $agentId, 'm3' => $agentId]);
if (!$st->fetchColumn()) {
    api_error('forbidden', $agent['display_name'] . ' holds no access to ' . $app['name'] . '.', 403);
}

// The prompt around the person's words: who is asking, from where, what was said before.
$lines = ['A person is asking you from the ' . $app['name'] . ' command bar. Answer them directly and briefly; do the work with your tools when the question needs it, and say plainly what you could not do or what paused for approval.',
          'Person: ' . $acting['display_name'] . ' (member ' . (int) $acting['id'] . ').'];
if ($screen !== '') {
    $lines[] = 'They are on the screen "' . $screen . '"' . ($context !== [] ? ' with context ' . json_encode($context, JSON_UNESCAPED_SLASHES) : '') . '.';
}
if ($conversation !== '') {
    $st = $pdo->prepare("SELECT chat_utterance, result FROM agent_runs
                          WHERE application_id = :a AND conversation_key = :c AND trigger = 'chat' AND status = 'succeeded'
                          ORDER BY id DESC LIMIT " . CHAT_HISTORY_TURNS);
    $st->execute(['a' => $app['id'], 'c' => $conversation]);
    $earlier = array_reverse($st->fetchAll());
    if ($earlier !== []) {
        $lines[] = 'Earlier in this conversation (oldest first):';
        array_push($lines, ...chat_history_lines($earlier, 600, 900));   // shared with the OS Chat tab (agent-chat.md)
    }
}
$lines[] = 'Their message: ' . $utterance;
$instructions = mb_substr(implode("\n", $lines), 0, AGENT_RUN_INSTRUCTIONS_MAX);

[$started, $error] = start_agent_run($agentId, $instructions, 'chat', null, (int) $acting['id']);
if ($error !== null) {
    api_error('conflict', $error, 409);
}
$runId = (int) $started['run_id'];
$pdo->prepare('UPDATE agent_runs SET application_id = :a, conversation_key = :c, chat_utterance = :u WHERE id = :r')
    ->execute(['a' => $app['id'], 'c' => $conversation === '' ? null : $conversation, 'u' => $utterance, 'r' => $runId]);
directory_log($pdo, 'application.chat', 'member', $agentId, ['agent_run_id' => $runId, 'request_id' => (string) $started['request_id'],
    'after' => ['run_id' => $runId, 'agent' => $agent['display_name'], 'screen' => $screen === '' ? null : $screen, 'conversation_id' => $conversation === '' ? null : $conversation]]);

set_time_limit(CHAT_WAIT_MAX + 20);
$deadline = microtime(true) + $wait;
$run = find_agent_run($pdo, $runId);
while ($run !== null && $run['status'] === 'running' && microtime(true) < $deadline) {
    usleep(500000);
    $run = find_agent_run($pdo, $runId);
}
if ($run !== null && $run['status'] !== 'running') {
    chat_stamp_ledger($pdo, $runId, $app['id']);
}
api_json(chat_answer($pdo, $run ?? ['id' => $runId, 'request_id' => $started['request_id'], 'status' => 'running', 'result' => null, 'error' => null,
    'approval_request_id' => null, 'conversation_key' => $conversation, 'cost' => null, 'currency' => null]), ($run['status'] ?? 'running') === 'running' ? 202 : 200);
