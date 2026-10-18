<?php
declare(strict_types=1);

/**
 * K6 (db/161): set the business's notification number — the one applications' texts are sent from.
 *
 *   php bin/notify_endpoint_set.php --address +18475550100 --account-sid AC… (--secret-id <tenant secret> | --token-stdin) [--by <email>]
 *   php bin/notify_endpoint_set.php --show
 *
 * The Twilio auth token is a tenant secret: name one that exists (--secret-id, e.g. the one an assistant's number
 * uses), or paste it on stdin (--token-stdin) to store a new one. It is never printed. The previous number is
 * deactivated. A number that is also an assistant's gets the assistant's replies — use a number of its own.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/secrets.php';

$o = getopt('', ['address:', 'account-sid:', 'secret-id:', 'token-stdin', 'by:', 'show']);
$pdo = db();
if (isset($o['show'])) {
    foreach ($pdo->query("SELECT id, channel, address, config->>'account_sid' AS sid, secret_id, active, created_at FROM notification_endpoints ORDER BY id") as $r) {
        printf("%d %s %s account %s secret #%s %s %s\n", $r['id'], $r['channel'], $r['address'], $r['sid'], $r['secret_id'] ?? '-', $r['active'] ? 'ACTIVE' : 'inactive', $r['created_at']);
    }
    exit(0);
}
$address = (string) ($o['address'] ?? '');
$sid = (string) ($o['account-sid'] ?? '');
if (!preg_match('/^\+[1-9][0-9]{7,14}$/', $address) || !preg_match('/^AC[0-9a-f]{32}$/', $sid) || (!isset($o['secret-id']) && !isset($o['token-stdin']))) {
    fwrite(STDERR, "Usage: --address +E164 --account-sid AC… (--secret-id N | --token-stdin) [--by email]  |  --show\n");
    exit(2);
}
$byEmail = (string) ($o['by'] ?? '');
$st = $pdo->prepare("SELECT id FROM members WHERE business_role = 'super_admin' AND status = 'active' AND member_kind = 'human'"
    . ($byEmail !== '' ? ' AND lower(email) = lower(:e)' : '') . ' ORDER BY id LIMIT 1');
$st->execute($byEmail !== '' ? ['e' => $byEmail] : []);
$by = (int) ($st->fetchColumn() ?: 0);
if ($by === 0) { fwrite(STDERR, "No such active super-admin.\n"); exit(1); }

if (isset($o['token-stdin'])) {
    $token = trim((string) stream_get_contents(STDIN));
    if (!preg_match('/^[0-9a-f]{32}$/', $token)) { fwrite(STDERR, "That is not a Twilio auth token.\n"); exit(2); }
    $secretId = store_tenant_secret($pdo, 'twilio-notify-' . $address, 'channel', 'twilio', $token, $by);
} else {
    $secretId = (int) $o['secret-id'];
    if (read_tenant_secret($pdo, $secretId) === null) { fwrite(STDERR, "No live tenant secret #{$secretId}.\n"); exit(1); }
}
$pdo->beginTransaction();
$pdo->exec("UPDATE notification_endpoints SET active = false, updated_at = now() WHERE channel = 'sms' AND active");
$ins = $pdo->prepare("INSERT INTO notification_endpoints (channel, address, secret_id, config, created_by) VALUES ('sms', :a, :s, CAST(:c AS jsonb), :b) RETURNING id");
$ins->execute(['a' => $address, 's' => $secretId, 'c' => json_encode(['account_sid' => $sid]), 'b' => $by]);
$id = (int) $ins->fetchColumn();
log_activity($pdo, 'notification_endpoint.set', 'notification_endpoint', $id, ['source' => 'cron', 'actor_member_id' => $by, 'after' => ['channel' => 'sms', 'address' => $address]]);
$pdo->commit();
$shared = $pdo->prepare("SELECT agent_member_id FROM agent_channel_endpoints WHERE channel = 'sms' AND address = :a AND active");
$shared->execute(['a' => $address]);
echo "Notification number {$address} set (#{$id}).\n";
if ($shared->fetchColumn() !== false) { echo "Note: this number is also an assistant's — replies to application texts will reach the assistant.\n"; }
