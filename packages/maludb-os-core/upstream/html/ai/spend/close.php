<?php
declare(strict_types=1);

/**
 * Action `ai_period_close` — close a past month: its statement is rolled up one last time and
 * frozen; a call that arrives for it later is late and lands in the open month. Super-admin.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/statements.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$period = request_string('period');
$note = trim(request_string('note'));
$bounds = ai_period_bounds($period);
$refuse = static function (string $m): never { emit_action_status(false, ['errors' => [$m]]); respond_invalid([$m]); };
if ($bounds === null) {
    $refuse('A period is written YYYY-MM.');
}
[$start, $end] = $bounds;
if ($end >= gmdate('Y-m-01')) {
    $refuse('Only a past month can be closed; ' . $period . ' is still running.');
}
$existing = find_ai_period($pdo, $start);
if ($existing !== null && $existing['status'] === 'closed') {
    $refuse($period . ' is already closed.');
}
if (mb_strlen($note) > 500) {
    $refuse('Keep the note under 500 characters.');
}
check_approval($pdo, 'ai_period_close', 'ai_period.close', 'Close the AI ledger period ' . $period, ['period' => $period, 'note' => $note], 'ai_period', null);
$r = close_ai_period($pdo, $start, $end, (int) current_member_id(), $note === '' ? null : $note);
log_activity($pdo, 'ai_period.close', 'ai_period', null, ['after' => ['period' => $period, 'note' => $note] + $r]);
emit_action_status(true, ['did' => "Closed {$period}: {$r['lines']} lines, {$r['calls']} calls", 'location' => '/ai/spend/statements?period=' . $period]);
