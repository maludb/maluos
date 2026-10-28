<?php
declare(strict_types=1);

/**
 * Screen `prompt-log` — model calls (params: agent, status, request_id, run, period, page; and, so an
 * aggregate row elsewhere can open its calls — click-around step 4: acting, model, provider, department,
 * application, month=YYYY-MM). Any
 * insider may open it; mcp_prompt_ledger shows the `ledger` grant everything, a person their own
 * calls, and an agent's calls to whoever may see that agent. No payload is ever in this list.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/records/present.php';

require_insider();

$pdo = db();
$period = isset(AIOPS_PERIODS[request_string('period')]) ? request_string('period') : 'this_month';
$status = request_string('status');
$month = preg_match('/^\d{4}-\d{2}$/', request_string('month')) === 1 && aiops_month(request_string('month')) !== null ? request_string('month') : '';
$day = preg_match('/^\d{4}-\d{2}-\d{2}$/', request_string('day')) === 1 && checkdate((int) substr(request_string('day'), 5, 2), (int) substr(request_string('day'), 8, 2), (int) substr(request_string('day'), 0, 4)) ? request_string('day') : '';
$pointed = request_integer('run') !== null || trim(request_string('request_id')) !== '' || $month !== '' || $day !== '';   // a deep link means "these calls", whenever they were
$filters = ['agent' => request_integer('agent'), 'run' => request_integer('run'), 'period' => $pointed && request_string('period') === '' ? 'all' : $period,
    'status' => $status === 'failed' || isset(AIOPS_CALL_STATUSES[$status]) ? $status : '', 'request_id' => mb_substr(trim(request_string('request_id')), 0, 100),
    'acting' => request_integer('acting'), 'model' => request_integer('model'), 'provider' => mb_substr(trim(request_string('provider')), 0, 60),
    'department' => request_integer('department'), 'application' => request_integer('application'), 'month' => $month, 'day' => $day];
[$rows, $total, $totals] = find_ledger_calls($pdo, $filters, request_integer('page') ?? 1);
// What the deep-link filters are called, so the page can name them in its title and offer to clear each.
$nameOf = static function (string $sql, ?int $id) use ($pdo): ?string {
    if ($id === null) { return null; }
    $st = $pdo->prepare($sql); $st->execute(['id' => $id]); $n = $st->fetchColumn();
    return $n === false || $n === null ? null : (string) $n;
};
$filterLabels = [
    'acting' => $nameOf('SELECT display_name FROM mcp_team_directory WHERE member_id = :id', $filters['acting']),
    'model' => $nameOf('SELECT display_name FROM mcp_model_registry WHERE model_id = :id', $filters['model']),
    'department' => $nameOf('SELECT name FROM mcp_departments WHERE department_id = :id', $filters['department']),
    'application' => $nameOf('SELECT name FROM mcp_applications WHERE application_id = :id', $filters['application']),
    'month' => $month !== '' ? (new DateTimeImmutable($month . '-01', new DateTimeZone('UTC')))->format('F Y') : null,
    'day' => $day !== '' ? (new DateTimeImmutable($day, new DateTimeZone('UTC')))->format('D j M Y') : null,
];
log_screen_view($pdo, 'prompt-log');
$named = static fn (array $l): array => array_map(static fn (string $k, string $v): array => ['id' => $k, 'name' => $v], array_keys($l), $l);
respond_screen([
    'calls' => array_map('present_ledger_call', $rows),
    'total' => $total, 'page' => max(1, request_integer('page') ?? 1), 'page_size' => AIOPS_PAGE_SIZE,
    'totals' => ['cost' => (string) $totals['cost'], 'tokens' => (int) $totals['tokens'], 'failed' => (int) $totals['failed']],
    'filters' => $filters, 'filter_labels' => $filterLabels,
    'options' => ['periods' => $named(AIOPS_PERIODS), 'statuses' => $named(AIOPS_CALL_STATUSES),
                  'agents' => array_values(array_filter(array_map('present_member_option', selectable_members($pdo)), static fn (array $m): bool => $m['kind'] === 'agent'))],
    'can' => ['evals' => !is_agent_member() && has_module_grant('evals')],
]);
