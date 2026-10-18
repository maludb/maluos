<?php
declare(strict_types=1);

/**
 * GET /ai/spend/export.php?period=YYYY-MM&format=csv|json — the period statement as a file, the
 * document os.ledger-period/1 (A5). Streamed as an attachment through the React download route;
 * logged as ai_period.export. Gate: the ledger grant.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/statements.php';

require_module_grant('ledger');

$pdo = db();
$period = request_string('period');
$format = request_string('format', 'csv') === 'json' ? 'json' : 'csv';
$doc = ai_period_document($pdo, $period);
if ($doc === null) {
    http_response_code(404);
    header('Content-Type: text/plain');
    exit('A period is written YYYY-MM.');
}
log_activity($pdo, 'ai_period.export', 'ai_period', null, ['after' => ['period' => $period, 'format' => $format, 'lines' => count($doc['lines'])]]);
$name = 'ai-ledger-' . $period . '.' . $format;
header('X-Content-Type-Options: nosniff');
header('Content-Disposition: attachment; filename="' . $name . '"');
if ($format === 'json') {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($doc, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
} else {
    header('Content-Type: text/csv; charset=utf-8');
    echo ai_period_csv($doc);
}
