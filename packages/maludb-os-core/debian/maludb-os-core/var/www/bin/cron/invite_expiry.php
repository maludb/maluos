<?php
declare(strict_types=1);
// Daily: report invitations expiring within 2 days (informational; expired invites are
// already filtered at read time so nothing destructive happens).
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';

$pdo = db();
$count = (int) $pdo->query("SELECT count(*) FROM invitations WHERE accepted_at IS NULL AND revoked_at IS NULL AND expires_at BETWEEN now() AND now() + interval '2 days'")->fetchColumn();
log_activity($pdo, 'cron.run', null, null, ['source' => 'cron', 'after' => ['job' => 'invite_expiry', 'expiring_soon' => $count]]);
echo "invite_expiry: {$count} invitations expiring within 2 days\n";
