<?php
declare(strict_types=1);
// Every 5 minutes: a desk that stopped heartbeating (power, network, a crashed session) is offline after three
// missed beats (db/187, docs/build-specs/desk-enrolment.md). A desk says offline itself when its session ends;
// this is for the ones that could not.
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/desks.php';

$pdo = db();
$gone = desk_presence_sweep($pdo);
if ($gone !== []) {
    log_activity($pdo, 'cron.run', null, null, ['source' => 'cron', 'after' => ['job' => 'desk_presence', 'offline' => array_column($gone, 'name')]]);
}
echo 'desk_presence: ' . count($gone) . " desk(s) marked offline\n";
