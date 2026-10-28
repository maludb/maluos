<?php
declare(strict_types=1);
// Every 10 minutes: expire approval requests nobody decided in time and release the agent runs
// that waited on them. The screens sweep too when opened; this is for the hours nobody looks.
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/approvals/queries.php';

$pdo = db();
$expired = sweep_due_approvals($pdo);
log_activity($pdo, 'cron.run', null, null, ['source' => 'cron', 'after' => ['job' => 'approvals_expire', 'expired' => count($expired)]]);
echo 'approvals_expire: ' . count($expired) . " request(s) expired\n";
