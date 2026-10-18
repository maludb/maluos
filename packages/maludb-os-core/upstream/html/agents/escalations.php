<?php
declare(strict_types=1);

/** Escalations list (screen `escalations`). Gate: insider — reads are insider-open;
 *  mcp_agent_escalations itself further narrows to the recipient or app_can_see_agent(). */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';

require_insider();
agents_require_files();

$pdo = db();
$filters = escalation_list_filters();
$page = request_integer('page') ?? 1;
$rows = find_escalations($pdo, $filters, $page);
$total = (int) ($rows[0]['total_count'] ?? 0);
$data = [
    'escalations' => $rows, 'filters' => $filters, 'page' => $page,
    'totalPages' => max(1, (int) ceil($total / AGENT_PAGE_SIZE)),
    'agentOptions' => find_agent_member_options($pdo),
];

if (($_SERVER['HTTP_HX_TARGET'] ?? '') === 'escalations-list-results') {
    header('Vary: HX-Request');
    echo view('agents/partials/escalation-table.php', $data);
    exit;
}

log_screen_view($pdo, 'escalations');
if (wants_json()) {
    require_once dirname(__DIR__, 2) . '/app/features/agents/present.php';
    respond_screen([
        'escalations' => array_map('present_escalation', $rows),
        'page' => max(1, $page),
        'total_pages' => $data['totalPages'],
        'filters' => [
            'agent' => $filters['agent'] !== null ? (string) $filters['agent'] : '',
            'open' => !empty($filters['open']),
        ],
        'options' => ['agents' => array_map('present_agent_option', $data['agentOptions'])],
    ]);
}
render_screen('Escalations · ' . business_name($pdo), view('agents/escalations.php', $data),
    ['activeNav' => 'nav-agents', 'screen' => 'escalations']);
