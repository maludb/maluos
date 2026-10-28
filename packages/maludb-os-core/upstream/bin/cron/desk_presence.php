<?php
declare(strict_types=1);
// Every 5 minutes: a desk that stopped heartbeating (power, network, a crashed session) is offline after three
// missed beats (db/187, docs/build-specs/desk-enrolment.md). A desk says offline itself when its session ends;
// this is for the ones that could not.
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/desks.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/nodes.php';

// db/188: nodes too, every minute (a node heartbeats every 60 s; three missed is offline, and node_offline is raised).
$pdo = db();
$gone = desk_presence_sweep($pdo);
$nodes = node_presence_sweep($pdo);
if ($gone !== [] || $nodes !== []) {
    log_activity($pdo, 'cron.run', null, null, ['source' => 'cron', 'after' => ['job' => 'desk_presence', 'offline' => array_column($gone, 'name'), 'nodes_offline' => array_column($nodes, 'name')]]);
}
echo 'desk_presence: ' . count($gone) . ' desk(s) and ' . count($nodes) . " node(s) marked offline\n";
