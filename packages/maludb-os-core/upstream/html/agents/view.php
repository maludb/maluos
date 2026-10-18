<?php
declare(strict_types=1);

/** Agent detail (screen `agent-view`). Gate: insider (writes need mod:hr; see the tabs
 *  themselves — job_description, grants and budget are hidden below app_can_see_agent in SQL,
 *  so a plain insider simply sees less, never an error). */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';

require_insider();
agents_require_files();

$pdo = db();
$id = request_integer('id');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}
// The tab is normalised, and everything the template needs assembled, by agent_view_data().
// No tab asked for: the Chat tab opens first for an agent that can take a typed turn, Job for the rest (owner, 2026-09-29).
require_once dirname(__DIR__, 2) . '/app/features/agents/chat.php';
$tab = request_string('tab') ?: (agent_chat_unavailable_reason($agent) === null ? 'chat' : 'job');

log_screen_view($pdo, 'agent-view');
if (wants_json()) {
    require_once dirname(__DIR__, 2) . '/app/features/agents/present.php';
    require_once dirname(__DIR__, 2) . '/app/features/approvals/queries.php';
    require_once dirname(__DIR__, 2) . '/app/features/approvals/present.php';
    // A request nobody answered in time expires now, and a run with nothing left pending is
    // released — so "paused for an approval" on this page is always something someone can act on.
    sweep_due_approvals($pdo, $id);
    $data = agent_view_data($pdo, $agent, $tab);
    $canEdit = $data['isHr'] || $data['isManager'];
    $kind = (string) ($agent['agent_kind'] ?? 'subagent');
    // A voice agent has no Roster tab (db/091); asked for it, it gets the Job tab.
    $shownTab = $kind === 'voice' && $data['tab'] === 'roster' ? 'job' : $data['tab'];
    $currency = $agent['budget_currency'] ?? null;
    $pending = $data['pendingVersion'];
    // Every tab's key travels in one payload (as Applications and Projects do): a tab is a URL. Since
    // 2026-09-28 only the SHOWN tab's sections are filled — the rest are empty, the shape unchanged —
    // because loading all eight cost 45 statements and a MaluDB call on every click.
    $on = static fn (string ...$tabs): bool => in_array($shownTab, $tabs, true);
    require_once dirname(__DIR__, 2) . '/app/features/team/present.php';
    respond_screen([
        // department_links (click-around step 2): the departments with their ids, beside the names the view carries.
        'agent' => present_agent($agent) + ['department_links' => array_map('present_member_department', member_departments($pdo, $id))],
        'tab' => $shownTab,
        'version' => $data['version'] !== null ? present_agent_version($data['version'], $currency) : null,
        'pending_version' => $pending !== null
            ? ['id' => (int) $pending['config_version_id'], 'version_no' => (int) $pending['version_no']] : null,
        'tool_grants' => array_map('present_agent_tool_grant', $data['toolGrants']),
        // The Skills tab (owner, 2026-09-27): the set the next run carries, resolved as the runner resolves it.
        'skills' => !$on('skills') ? null : (static function () use ($pdo, $agent, $data): array {
            require_once dirname(__DIR__, 2) . '/app/features/skills/resolve.php';
            $runtime = $data['version']['runtime_config'] ?? [];
            $runtime = is_string($runtime) ? (json_decode($runtime, true) ?: []) : (array) $runtime;
            return resolve_agent_skills($pdo, $agent, $runtime);
        })(),
        'duties' => array_map('present_agent_duty', $data['duties']),
        'hr_events' => array_map('present_hr_event', $data['hrEvents']),
        'reviews' => array_map('present_performance_review', $data['reviews']),
        'approvals' => array_map('present_agent_approval_request', $data['approvalsForAgent']),
        // What the agent is stuck on (owner, 2026-09-27: whoever sees "paused for an approval" must be a
        // few clicks from releasing it): each paused run with its pending requests and what THIS
        // reader may do about each — decide as its approver, or withdraw as the agent's nearest human manager.
        'paused' => (static function () use ($pdo, $id): array {
            $me = (int) current_member_id();
            $human = !is_agent_member();
            $manager = $human ? nearest_human_manager($pdo, $id) : null;
            return array_map(static fn (array $run): array => [
                'id' => $run['id'], 'started_at' => json_ts($run['started_at']), 'trigger' => (string) $run['trigger'],
                'duty_name' => $run['duty_name'] ?? null,
                'requests' => array_map(static fn (array $r): array => present_approval_request($r) + [
                    'can' => ['decide' => $human && (int) $r['approver_member_id'] === $me, 'cancel' => $manager === $me],
                ], $run['requests']),
            ], find_paused_runs_for_agent($pdo, $id));
        })(),
        // The Inbox tab (db/155-156): messages to and from the agent — through mcp_agent_messages, so only
        // what this reader may see — and the channels (bot, number, mailbox) it answers on.
        'inbox' => !$on('inbox') ? ['messages' => [], 'endpoints' => []] : (static function () use ($pdo, $id): array {
            $st = $pdo->prepare('SELECT message_id, thread_id, thread_subject, from_member_id, from_name, from_kind, to_member_id,
                                        to_name, to_kind, kind, priority, subject, body, channel, status, created_at
                                   FROM mcp_agent_messages WHERE :a IN (from_member_id, to_member_id) ORDER BY created_at DESC LIMIT 60');
            $st->execute(['a' => $id]);
            $e = $pdo->prepare('SELECT channel, address FROM agent_channel_endpoints WHERE agent_member_id = :a AND active ORDER BY channel');
            $e->execute(['a' => $id]);
            return [
                'messages' => array_map(static fn (array $m): array => [
                    'id' => (int) $m['message_id'], 'thread_id' => (int) $m['thread_id'], 'thread_subject' => (string) $m['thread_subject'],
                    'outgoing' => (int) $m['from_member_id'] === $id, 'other_id' => (int) ((int) $m['from_member_id'] === $id ? $m['to_member_id'] : $m['from_member_id']),
                    'other_name' => (string) ((int) $m['from_member_id'] === $id ? $m['to_name'] : $m['from_name']),
                    'other_kind' => (string) ((int) $m['from_member_id'] === $id ? $m['to_kind'] : $m['from_kind']),
                    'kind' => (string) $m['kind'], 'priority' => (string) $m['priority'], 'subject' => (string) $m['subject'],
                    'body' => (string) $m['body'], 'channel' => (string) $m['channel'], 'status' => (string) $m['status'],
                    'created_at' => json_ts($m['created_at']),
                ], $st->fetchAll()),
                'endpoints' => array_map(static fn (array $x): array => ['channel' => (string) $x['channel'], 'address' => (string) $x['address']], $e->fetchAll()),
            ];
        })(),
        // The Chat tab (agent-chat.md, db/163): this person's conversations with this agent, the open one's turns, and
        // whether the agent can take a message now. Conversations are private to their person; the turns are theirs.
        'chat' => !$on('chat') ? null : (static function () use ($pdo, $agent, $id): array {
            require_once dirname(__DIR__, 2) . '/app/features/agents/chat.php';
            $me = (int) current_member_id();
            $archived = request_string('archived') === '1';
            $list = find_agent_conversations($pdo, $id, $me, $archived);
            $open = request_integer('c');
            // ?c=<id> opens one; ?c=new is a blank page for a new conversation; neither opens the newest.
            $conversation = request_string('c') === 'new' ? null : ($open !== null ? find_agent_conversation($pdo, $open, $me, $id) : ($list[0] ?? null));
            $can = agent_chat_availability($pdo, $agent);
            return [
                'can_send' => $can['can'] && !is_agent_member() && ($conversation === null || $conversation['archived_at'] === null),
                'reason' => $can['reason'], 'busy_run_id' => $can['busy_run_id'],
                'archived_view' => $archived,
                'conversations' => array_map('present_chat_conversation', $list),
                'conversation' => $conversation !== null ? present_chat_conversation($conversation) : null,
                'turns' => $conversation !== null ? array_map('present_chat_turn', find_conversation_turns($pdo, (int) $conversation['id'])) : [],
                'message_max' => AGENT_CHAT_MESSAGE_MAX,
            ];
        })(),
        'counts' => [
            'activity' => (int) $data['activityCount'],
            'escalations' => count($data['escalationsForAgent']),
            'approvals' => count($data['approvalsForAgent']),
        ],
        // Everything about the agent on its own page (owner, 2026-09-27): its model calls, runs,
        // spend and evaluations come from the same views AI Ops reads, so the ledger and run
        // gates (app_can_see_run) and the evals gate (app_can_see_evals) decide what a reader
        // sees here exactly as they do there. Evals are people's work: an agent caller gets none.
        'ops' => (static function () use ($pdo, $id, $on): array {
            require_once dirname(__DIR__, 2) . '/app/features/aiops/queries.php';
            require_once dirname(__DIR__, 2) . '/app/features/aiops/present.php';
            if (!$on('performance')) {   // the shape, empty: the ledger and runs are the page's dearest reads
                $none = ['calls' => 0, 'failed' => 0, 'input_tokens' => 0, 'output_tokens' => 0, 'cache_read_tokens' => 0,
                         'avg_latency_ms' => null, 'cost' => 0, 'currency' => 'USD', 'last_at' => null];
                return ['ledger' => array_map('present_agent_ledger_period', ['this_month' => $none, 'last_month' => $none, 'all' => $none]),
                        'calls' => [], 'runs' => [], 'evals' => null,
                        'run_counts' => ['total' => 0, 'active' => 0, 'failed' => 0, 'succeeded' => 0, 'last_started_at' => null]];
            }
            [$calls] = find_ledger_calls($pdo, ['agent' => $id, 'period' => 'all'], 1);
            $runs = summarise_agent_runs($pdo, $id);
            $evals = is_agent_member() ? null : [
                'sets' => array_map('present_eval_set', find_eval_sets($pdo, $id)),
                'runs' => array_map('present_eval_run', find_agent_eval_runs($pdo, $id)),
                'alerts' => array_map('present_eval_alert', find_eval_alerts($pdo, ['agent' => $id])),
            ];
            return [
                'ledger' => array_map('present_agent_ledger_period', summarise_agent_ledger($pdo, $id)),
                'calls' => array_map('present_ledger_call', array_slice($calls, 0, 10)),
                'runs' => array_map('present_ops_run', find_agent_runs($pdo, $id)),
                'run_counts' => ['total' => (int) $runs['total'], 'active' => (int) $runs['active'], 'failed' => (int) $runs['failed'],
                                 'succeeded' => (int) $runs['succeeded'], 'last_started_at' => json_ts($runs['last_started_at'] ?? null)],
                'evals' => $evals,
            ];
        })(),
        // A system_one agent (db/145): its mode and the playbooks its duties run; the switch is the super-admin's.
        'system_one' => (static function () use ($pdo, $agent, $data): ?array {
            $v = $data['version'];
            if ($v === null) { return null; }
            $st = $pdo->prepare('SELECT harness FROM model_registry WHERE id = :id');
            $st->execute(['id' => (int) $v['model_id']]);
            if ($st->fetchColumn() !== 'system_one') { return null; }
            $st = $pdo->prepare('SELECT runtime_config FROM agent_config_versions WHERE id = :id');
            $st->execute(['id' => (int) $v['config_version_id']]);
            $rc = json_decode((string) ($st->fetchColumn() ?: '{}'), true) ?: [];
            return ['mode' => ($rc['mode'] ?? 'shadow') === 'live' ? 'live' : 'shadow', 'can_switch' => is_super_admin()];
        })(),
        'roster' => array_map(static fn (array $r): array => present_roster_row($r, $kind === 'orchestrator'),
            $data['roster']),
        // The pickers are sent only to someone who may use them.
        'options' => [
            'managers' => $canEdit ? array_map('present_manager_option', $data['managerOptions']) : [],
            'tool_endpoints' => $canEdit ? array_map('present_tool_endpoint_option', $data['toolEndpointOptions']) : [],
            'subagents' => $canEdit ? array_map('present_agent_option', $data['subagentOptions']) : [],
        ],
        'can' => ['edit' => $canEdit, 'offboard' => $canEdit && is_super_admin()],
    ]);
}
render_screen(($agent['display_name'] ?? 'Agent') . ' · ' . business_name($pdo),
    view('agents/agent.php', agent_view_data($pdo, $agent, $tab)),  // one contract, one place
    ['activeNav' => 'nav-agents', 'screen' => 'agent-view', 'entity' => 'member', 'recordId' => (string) $id]);
