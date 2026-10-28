<?php
declare(strict_types=1);

/** Agents list (screen `agents-list`). Gate: insider — who works here and what their job is,
 *  is not a secret from the people they work with (H1's audience is literally `all`). */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';

require_insider();
agents_require_files();

$pdo = db();
$filters = agent_list_filters();
$page = request_integer('page') ?? 1;
$agents = find_agents($pdo, $filters, $page);
$total = (int) ($agents[0]['total_count'] ?? 0);
$data = [
    'agents' => $agents, 'filters' => $filters, 'page' => $page,
    'totalPages' => max(1, (int) ceil($total / AGENT_PAGE_SIZE)),
    'departments' => find_departments($pdo),
];

if (($_SERVER['HTTP_HX_TARGET'] ?? '') === 'agents-list-results') {
    header('Vary: HX-Request');
    echo view('agents/partials/agent-table.php', $data);
    exit;
}

log_screen_view($pdo, 'agents-list');
if (wants_json()) {
    require_once dirname(__DIR__, 2) . '/app/features/agents/present.php';
    require_once dirname(__DIR__, 2) . '/app/features/records/present.php';
    respond_screen([
        'agents' => array_map('present_agent_row', $agents),
        'page' => max(1, $page),
        'total_pages' => $data['totalPages'],
        'filters' => [
            'status' => in_array($filters['status'], AGENT_STATUSES, true) ? $filters['status'] : '',
            'department' => $filters['department'] !== null ? (string) $filters['department'] : '',
        ],
        'options' => ['departments' => array_map('present_department_option', $data['departments'])],
        'can' => ['admin' => is_business_admin()],
    ]);
}
render_screen('Agent HR · ' . business_name($pdo), view('agents/agents.php', $data),
    ['activeNav' => 'nav-agents', 'screen' => 'agents-list']);
