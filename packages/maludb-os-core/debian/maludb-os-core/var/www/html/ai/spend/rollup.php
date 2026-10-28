<?php
declare(strict_types=1);

/** Action `ai_period_rollup` — recompute an open month's statement from the ledger. Gate: ledger grant. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/statements.php';

require_module_grant('ledger');
require_post();
verify_csrf();

$pdo = db();
$period = request_string('period');
$bounds = ai_period_bounds($period);
if ($bounds === null) {
    emit_action_status(false, ['errors' => ['A period is written YYYY-MM.']]);
    respond_invalid(['A period is written YYYY-MM.']);
}
[$start, $end] = $bounds;
try {
    $r = rollup_ai_period($pdo, $start, $end);
} catch (RuntimeException $e) {
    emit_action_status(false, ['errors' => [$e->getMessage()]]);
    respond_invalid([$e->getMessage()]);
}
log_activity($pdo, 'ai_period.rollup', 'ai_period', null, ['after' => ['period' => $period] + $r]);
emit_action_status(true, ['did' => "Rolled up {$period}: {$r['lines']} lines, {$r['calls']} calls" . ($r['late_calls'] > 0 ? " ({$r['late_calls']} late)" : ''),
    'location' => '/ai/spend/statements?period=' . $period]);
