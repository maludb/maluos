<?php
declare(strict_types=1);

/**
 * GET /api/v1/ledger/periods.php?period=YYYY-MM — the period statement for an application from us
 * (the accounting application's timer), the document os.ledger-period/1 (A5). Internal port only;
 * bearer = the application's token (app/api/directory.php). Without `period`, the months and their
 * status, so the caller knows what is closed. Logged as ai_period.export with source application.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/api/directory.php';
require_once dirname(__DIR__, 4) . '/app/features/aiops/statements.php';

api_require_get();
directory_authenticate();
$pdo = db();

$period = trim((string) ($_GET['period'] ?? ''));
if ($period === '') {
    api_json(['schema' => 'os.ledger-periods/1', 'periods' => array_map(static fn (array $m): array => [
        'period' => $m['period'], 'period_start' => (string) $m['period_start'], 'period_end' => (string) $m['period_end'], 'status' => (string) $m['status'],
        'closed_at' => json_ts($m['closed_at'] ?? null), 'statement_lines' => (int) $m['statement_lines'], 'ledger_calls' => (int) $m['ledger_calls'],
    ], find_ai_period_months($pdo))]);
}
$doc = ai_period_document($pdo, $period);
if ($doc === null) {
    api_error('invalid', 'period is written YYYY-MM.', 422);
}
directory_log($pdo, 'ai_period.export', 'ai_period', null, ['after' => ['period' => $period, 'format' => 'feed', 'lines' => count($doc['lines'])]]);
api_json($doc);
