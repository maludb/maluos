<?php
declare(strict_types=1);

/**
 * Screen `ai-statements` (GET /ai/spend/statements.php?period=YYYY-MM) — the ledger's period
 * statements (A5): every month, its status, what the ledger says and what the statement says;
 * the chosen month's lines. Gate: the ledger grant (business-wide data), super-admin included.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/statements.php';

require_module_grant('ledger');

$pdo = db();
$months = find_ai_period_months($pdo);
$period = request_string('period');
if (ai_period_bounds($period) === null) {
    $period = $months[0]['period'] ?? gmdate('Y-m');
}
[$start, $end] = ai_period_bounds($period);
$selected = find_ai_period($pdo, $start);
log_screen_view($pdo, 'ai-statements');
respond_screen([
    'period' => $period,
    'months' => array_map('present_ai_period_month', $months),
    'selected' => [
        'period' => $period, 'period_start' => $start, 'period_end' => $end,
        'status' => $selected['status'] ?? 'open',
        'closed_at' => json_ts($selected['closed_at'] ?? null), 'closed_by_name' => $selected['closed_by_name'] ?? null,
        'closed_by' => isset($selected['closed_by']) ? (int) $selected['closed_by'] : null,
        'rolled_up_at' => json_ts($selected['rolled_up_at'] ?? null), 'note' => $selected['note'] ?? null,
        'is_past' => $end < gmdate('Y-m-01'),
    ],
    'lines' => array_map('present_ai_statement_line', find_ai_statement_lines($pdo, $start)),
    'can' => ['rollup' => ($selected['status'] ?? 'open') === 'open', 'close' => is_super_admin() && ($selected['status'] ?? 'open') === 'open' && $end < gmdate('Y-m-01')],
]);
