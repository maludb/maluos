<?php
declare(strict_types=1);

/**
 * Agent config history (screen `agent-versions`). Served as /agents/versions?agent={id} — a
 * three-segment path with the id in the middle has no installed rewrite rule (the ledger slice
 * learned this the hard way), so this is the same substitution as bank-import. Gate: insider.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';

require_insider();
agents_require_files();

$pdo = db();
$id = request_integer('agent');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}

log_screen_view($pdo, 'agent-versions');
if (wants_json()) {
    require_once dirname(__DIR__, 2) . '/app/features/agents/present.php';
    $currency = $agent['budget_currency'] ?? null;
    respond_screen([
        'agent' => present_agent($agent),
        'versions' => array_map(static fn (array $v): array => present_agent_version($v, $currency, false),
            find_agent_versions($pdo, $id)),
        'can' => ['edit' => has_module($pdo, 'hr')
            || (int) ($agent['manager_member_id'] ?? 0) === (int) current_member_id()],
    ]);
}
render_screen('Config history · ' . ($agent['display_name'] ?? 'Agent') . ' · ' . business_name($pdo),
    view('agents/versions.php', [
        'agent' => $agent,
        'versions' => find_agent_versions($pdo, $id),
        'isHr' => has_module($pdo, 'hr'),
        'isManager' => (int) ($agent['manager_member_id'] ?? 0) === (int) current_member_id(),
        'errors' => [],
    ]),
    ['activeNav' => 'nav-agents', 'screen' => 'agent-versions', 'entity' => 'member', 'recordId' => (string) $id]);
