<?php
declare(strict_types=1);

/**
 * Screen `ai-ops` (GET /ai/) — the AI Ops front page (owner, 2026-09-27: "/ai should be a real index
 * page"): each section's headline numbers, so the crumb "AI Ops" lands somewhere that says what is
 * going on and where to look. Any insider; what a section shows is what its own screen would show
 * this person (the ledger views decide the calls, evals need a person, Audit and System need an
 * admin — those two are null for anyone else, and the page leaves them out).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 2) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 2) . '/app/features/aiops/present.php';

require_insider();

$pdo = db();
log_screen_view($pdo, 'ai-ops');

$one = static function (string $sql, array $args = []) use ($pdo): array {
    $st = $pdo->prepare($sql); $st->execute($args);
    return $st->fetch() ?: [];
};

// Spend and calls: this month, from the same query the Spend page sums (what this person may see).
$rows = find_ai_spend($pdo, 'this_month', 'provider');
$spend = [
    'cost' => number_format(array_sum(array_map('floatval', array_column($rows, 'cost'))), 4, '.', ''),
    'currency' => $rows[0]['currency'] ?? 'USD',
    'calls' => array_sum(array_column($rows, 'calls')), 'failed' => array_sum(array_column($rows, 'failed')),
    'tokens' => array_sum(array_column($rows, 'input_tokens')) + array_sum(array_column($rows, 'output_tokens')),
    'providers' => array_map(static fn (array $r): array => ['name' => (string) $r['label'], 'cost' => (string) $r['cost']], array_slice($rows, 0, 3)),
];
[, $today, $t] = find_ledger_calls($pdo, ['period' => 'today', 'status' => '', 'request_id' => ''], 1);
$log = ['calls_today' => (int) $today, 'failed_today' => (int) $t['failed'], 'cost_today' => (string) $t['cost']];

// The month's statement.
$month = gmdate('Y-m');
$period = $one('SELECT period, status, closed_at FROM mcp_ai_periods WHERE period = :p', ['p' => $month]);
$statements = ['period' => $month, 'status' => $period['status'] ?? 'open', 'closed_at' => json_ts($period['closed_at'] ?? null)];

// Evals, watch and traces: people's work; an agent gets null and the page leaves them out.
$evals = null;
if (!is_agent_member()) {
    $sets = $one("SELECT count(*) FILTER (WHERE status = 'active') AS active, count(*) AS total FROM mcp_eval_sets");
    $last = $one('SELECT eval_run_id, eval_set_name, status, score, finished_at FROM mcp_eval_runs ORDER BY started_at DESC NULLS LAST, eval_run_id DESC LIMIT 1');
    $alerts = $one("SELECT count(*) FILTER (WHERE status <> 'resolved') AS open, count(*) FILTER (WHERE status = 'open' AND severity = 'critical') AS critical FROM mcp_eval_alerts");
    $sched = $one('SELECT count(*) FILTER (WHERE active) AS active FROM mcp_eval_schedules');
    $traces = $one('SELECT count(*) AS graded, count(*) FILTER (WHERE passed = false) AS failed FROM mcp_trace_grades');
    $evals = [
        'sets_active' => (int) ($sets['active'] ?? 0), 'sets_total' => (int) ($sets['total'] ?? 0),
        'last_run' => $last !== [] ? ['id' => (int) $last['eval_run_id'], 'set_name' => (string) $last['eval_set_name'], 'status' => (string) $last['status'],
                                     'score' => $last['score'] !== null ? (string) $last['score'] : null, 'finished_at' => json_ts($last['finished_at'] ?? null)] : null,
        'alerts_open' => (int) ($alerts['open'] ?? 0), 'alerts_critical' => (int) ($alerts['critical'] ?? 0),
        'schedules_active' => (int) ($sched['active'] ?? 0),
        'traces_graded' => (int) ($traces['graded'] ?? 0), 'traces_failed' => (int) ($traces['failed'] ?? 0),
    ];
}

// Audit and System: the super-admin and business admins, as their screens are gated.
$ops = null;
if (is_super_admin() || is_business_admin()) {
    $probes = $one("SELECT count(*) AS total, count(*) FILTER (WHERE status = 'failed') AS failed, count(*) FILTER (WHERE status = 'warning') AS warning FROM mcp_system_probes");
    $events = $one("SELECT count(*) FILTER (WHERE status IN ('open', 'acknowledged')) AS open FROM mcp_system_events");
    $audit = $one("SELECT count(*) FILTER (WHERE playbook IN ('scheduled_evals', 'trace_sampling', 'evidence_integrity') AND decision <> 'record' AND created_at >= now() - interval '7 days') AS audit_decisions,
                          count(*) FILTER (WHERE playbook IN ('health', 'logs_and_guardrails') AND decision <> 'record' AND created_at >= now() - interval '7 days') AS system_decisions
                     FROM mcp_system_one_decisions");
    $ops = ['probes_total' => (int) ($probes['total'] ?? 0), 'probes_failed' => (int) ($probes['failed'] ?? 0), 'probes_warning' => (int) ($probes['warning'] ?? 0),
            'events_open' => (int) ($events['open'] ?? 0),
            'audit_decisions_7d' => (int) ($audit['audit_decisions'] ?? 0), 'system_decisions_7d' => (int) ($audit['system_decisions'] ?? 0)];
}

$models = $one("SELECT count(*) FILTER (WHERE status = 'active') AS active, count(*) AS total FROM mcp_model_registry");

respond_screen([
    'spend' => $spend, 'log' => $log, 'statements' => $statements, 'evals' => $evals, 'ops' => $ops,
    'models' => ['active' => (int) ($models['active'] ?? 0), 'total' => (int) ($models['total'] ?? 0)],
]);
