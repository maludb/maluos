<?php
declare(strict_types=1);

/**
 * Business home (screen id `dashboard`) — the shape of the business in counts, then one card
 * per agent. The business dashboard takes '/' at the shell conversion (action manifest,
 * decision 9); the cert-study dashboard lives on at /study/.
 *
 * Build plan 1.10 shipped this as the manifest's overview over a period selector. The owner
 * took the cards off one by one on 2026-09-18 — money, pipeline and "Waiting on you" first,
 * then AI activity and the recent trail — so nothing here reads over a period any more and the
 * selector went with them. The removed cards' queries stay in app/features/home/queries.php,
 * so restoring one is a view change rather than a rebuild; the trail itself lives on at
 * /activity, which is the screen built for reading it.
 */
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/home/queries.php';
// agent_avatar_html(): the agent cards show the same picture, with the same initials
// fallback, that the agents list and the agent's own page show.
require_once dirname(__DIR__) . '/app/features/agents/render.php';

require_login();

$pdo = db();

require_once dirname(__DIR__) . '/app/features/approvals/queries.php';
sweep_due_approvals($pdo);     // an overdue request expires and its run is released before the cards say "paused"
$agents = home_agents($pdo);
$data = [
    'agents'     => $agents,
    'agentTotal' => (int) ($agents[0]['total_count'] ?? 0),
    'viewerTz'   => current_member()['timezone'] ?? 'UTC',
];

// The agent grid refreshes itself on hiring and once a minute, and asks for itself by name.
// A fragment is not a screen view, so this branch logs none.
if (($_SERVER['HTTP_HX_TARGET'] ?? '') === 'home-agents') {
    header('Vary: HX-Request');
    echo view('home/partials/agent-cards.php', $data);
    exit;
}

log_screen_view($pdo, 'dashboard');
if (wants_json()) {
    require_once dirname(__DIR__) . '/app/features/home/present.php';
    $viewerTz = $data['viewerTz'];
    respond_screen([
        'brand' => business_name($pdo),
        'counts' => present_home_counts(home_counts($pdo)),
        'agents' => array_map(static fn (array $a): array => present_home_agent($a, $viewerTz), $agents),
        'agent_total' => $data['agentTotal'],
        // The people who work here, under the agents (2026-09-26): every human the directory holds,
        // offboarded ones aside; the super-admin maintains them from Human Workforce (/team?kind=human).
        'team_members' => (static function () use ($pdo, $viewerTz): array {
            require_once dirname(__DIR__) . '/app/features/team/present.php';
            $rows = $pdo->query("SELECT * FROM mcp_team_directory WHERE member_kind = 'human' AND status <> 'offboarded'
                                  ORDER BY status = 'active' DESC, display_name LIMIT 500")->fetchAll();
            return array_map(static function (array $m) use ($viewerTz): array {
                $words = preg_split('/\s+/', trim((string) $m['display_name'])) ?: [];
                $initials = strtoupper(implode('', array_map(static fn (string $w): string => mb_substr($w, 0, 1), array_slice($words, 0, 2))));
                return [
                    'id' => (int) $m['member_id'],
                    'display_name' => (string) $m['display_name'],
                    'initials' => $initials !== '' ? $initials : '?',
                    'job_title' => ($m['job_title'] ?? '') !== '' ? (string) $m['job_title'] : null,
                    'business_role' => (string) $m['business_role'],
                    'status' => (string) $m['status'],
                    'departments' => present_pg_names($m['departments'] ?? null),
                    'department_links' => present_department_links($m),
                    'last_login_display' => ($l = format_ts($m['last_login_at'] ?? null, $viewerTz)) !== '' ? $l : null,
                ];
            }, $rows);
        })(),
    ]);
}
render_screen('Home · ' . business_name($pdo),
    view('home/page.php', $data + ['brand' => business_name($pdo), 'counts' => home_counts($pdo)]),
    ['activeNav' => 'nav-dashboard', 'screen' => 'dashboard']);
