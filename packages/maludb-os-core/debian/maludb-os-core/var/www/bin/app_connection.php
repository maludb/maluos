<?php
declare(strict_types=1);

/**
 * K7 (db/161): the connections between applications — one application reading another's shared tool.
 *
 *   php bin/app_connection.php list
 *   php bin/app_connection.php approve <connection id> [--by <super-admin email>]
 *   php bin/app_connection.php revoke  <connection id> [--by <super-admin email>]
 *
 * The installer proposes a connection from the consumer's maludb-os.json reads[]; only a super-admin's approval
 * lets the kernel make the call. Revoked, never deleted.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/applications/services.php';

$args = array_values(array_filter(array_slice($argv, 1), static fn ($a) => !str_starts_with($a, '--')));
$o = getopt('', ['by:']);
$pdo = db();
$cmd = $args[0] ?? 'list';
if ($cmd === 'list') {
    $rows = $pdo->query("SELECT c.id, ca.name AS consumer, pa.name AS provider, c.tool, c.why,
                                CASE WHEN c.revoked_at IS NOT NULL THEN 'revoked' WHEN c.approved_at IS NOT NULL THEN 'approved' ELSE 'proposed' END AS state,
                                s.scoped, s.people, s.withdrawn_at
                           FROM application_connections c JOIN applications ca ON ca.id = c.consumer_id JOIN applications pa ON pa.id = c.provider_id
                           LEFT JOIN application_shares s ON s.application_id = c.provider_id AND s.tool = c.tool ORDER BY c.id")->fetchAll();
    foreach ($rows as $r) {
        printf("#%d %-9s %s reads %s.%s%s%s — %s\n", $r['id'], $r['state'], $r['consumer'], $r['provider'], $r['tool'],
            $r['scoped'] === null ? ' (not shared yet)' : (($r['scoped'] ? ' (per site)' : '') . ($r['people'] ? ' (about people)' : '')), $r['withdrawn_at'] ? ' (withdrawn)' : '', $r['why']);
    }
    if ($rows === []) { echo "No connections.\n"; }
    exit(0);
}
if (!in_array($cmd, ['approve', 'revoke'], true) || (int) ($args[1] ?? 0) <= 0) {
    fwrite(STDERR, "Usage: list | approve <id> | revoke <id> [--by email]\n");
    exit(2);
}
$byEmail = (string) ($o['by'] ?? '');
$st = $pdo->prepare("SELECT id FROM members WHERE business_role = 'super_admin' AND status = 'active' AND member_kind = 'human'"
    . ($byEmail !== '' ? ' AND lower(email) = lower(:e)' : '') . ' ORDER BY id LIMIT 1');
$st->execute($byEmail !== '' ? ['e' => $byEmail] : []);
$by = (int) ($st->fetchColumn() ?: 0);
if ($by === 0) { fwrite(STDERR, "No such active super-admin.\n"); exit(1); }
try {
    $c = application_connection_decide($pdo, (int) $args[1], $cmd, $by);
    echo "Connection #{$c['id']} " . ($cmd === 'approve' ? 'approved' : 'revoked') . ".\n";
} catch (RuntimeException $e) {
    fwrite(STDERR, $e->getMessage() . "\n");
    exit(1);
}
