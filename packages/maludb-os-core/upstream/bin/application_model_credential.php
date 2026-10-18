<?php
declare(strict_types=1);

/**
 * K24 (db/171): an application's credential at the ledger proxy — what a memory engine behind an application (Knowledge's MaluDB) sends as
 * its provider API key, so the engine's model calls are priced, ledgered, stamped with the application and land on the AI statement.
 *
 *   php bin/application_model_credential.php mint   --app <catalog_key|id> --models key1,key2 [--budget 50.00] [--label text] [--by <email>]
 *   php bin/application_model_credential.php revoke --app <catalog_key|id>
 *   php bin/application_model_credential.php list
 *
 * --models names model_registry model_keys (api_key models only; every one must be registered with a price — an embedding model
 * too). The raw credential (appm_ + 48 hex) is printed ONCE by `mint` and nowhere else; only its sha256 is kept. Minting again
 * revokes the last. The endpoint it is used at: the ledger proxy, /openai/v1 (chat, embeddings) or /anthropic/v1.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';

$cmd = $argv[1] ?? '';
// PHP's getopt() stops at the first non-option (the command word), so the --flags are read by hand.
$o = [];
for ($i = 2; $i < count($argv); $i++) {
    if (preg_match('/^--([a-z]+)(?:=(.*))?$/', $argv[$i], $m)) { $o[$m[1]] = $m[2] ?? ($argv[++$i] ?? ''); }
}
$pdo = db();

function resolve_app(PDO $pdo, string $ref): array
{
    $st = $pdo->prepare('SELECT id, name, status FROM applications WHERE ' . (ctype_digit($ref) ? 'id = :r::bigint' : 'catalog_key = :r'));
    $st->execute(['r' => $ref]);
    $a = $st->fetch();
    if (!$a) { fwrite(STDERR, "No such application: {$ref}\n"); exit(1); }
    return $a;
}

if ($cmd === 'list') {
    foreach ($pdo->query("SELECT c.id, a.name, c.label, c.allowed_model_ids, c.monthly_budget_amount, c.created_at, c.last_used_at, c.revoked_at
                            FROM application_model_credentials c JOIN applications a ON a.id = c.application_id ORDER BY c.id") as $r) {
        printf("#%d %s '%s' models %s budget %s minted %s last used %s %s\n", $r['id'], $r['name'], $r['label'], $r['allowed_model_ids'],
            $r['monthly_budget_amount'] ?? 'none', $r['created_at'], $r['last_used_at'] ?? 'never', $r['revoked_at'] ? 'REVOKED ' . $r['revoked_at'] : 'LIVE');
    }
    exit(0);
}
if ($cmd === 'revoke') {
    $a = resolve_app($pdo, (string) ($o['app'] ?? ''));
    $st = $pdo->prepare('UPDATE application_model_credentials SET revoked_at = now() WHERE application_id = :a AND revoked_at IS NULL');
    $st->execute(['a' => $a['id']]);
    log_activity($pdo, 'application.model_credential_revoke', 'application', (int) $a['id'], ['source' => 'cron', 'after' => ['revoked' => $st->rowCount()]]);
    echo "Revoked {$st->rowCount()} live credential(s) of {$a['name']}.\n";
    exit(0);
}
if ($cmd !== 'mint') { fwrite(STDERR, "Usage: mint|revoke|list — see the header of this file.\n"); exit(2); }

$a = resolve_app($pdo, (string) ($o['app'] ?? ''));
if (!in_array($a['status'], ['active', 'degraded'], true)) { fwrite(STDERR, "Only an active application holds a credential; this one is {$a['status']}.\n"); exit(1); }
$keys = array_values(array_filter(array_map('trim', explode(',', (string) ($o['models'] ?? '')))));
if ($keys === []) { fwrite(STDERR, "--models is required (model_registry keys).\n"); exit(2); }
$in = implode(',', array_fill(0, count($keys), '?'));
$st = $pdo->prepare("SELECT id, model_key FROM model_registry WHERE model_key IN ($in) AND status = 'active' AND auth_mode = 'api_key'");
$st->execute($keys);
$found = $st->fetchAll(PDO::FETCH_KEY_PAIR);
$missing = array_diff($keys, array_values($found));
if ($missing !== []) { fwrite(STDERR, 'Not active api_key models in the registry: ' . implode(', ', $missing) . "\n"); exit(1); }
$budget = isset($o['budget']) ? (string) $o['budget'] : null;
if ($budget !== null && !preg_match('/^\d+(\.\d{1,2})?$/', $budget)) { fwrite(STDERR, "--budget is an amount like 50.00.\n"); exit(2); }
$byEmail = (string) ($o['by'] ?? '');
$st = $pdo->prepare("SELECT id FROM members WHERE business_role = 'super_admin' AND status = 'active' AND member_kind = 'human'"
    . ($byEmail !== '' ? ' AND lower(email) = lower(:e)' : '') . ' ORDER BY id LIMIT 1');
$st->execute($byEmail !== '' ? ['e' => $byEmail] : []);
$by = (int) ($st->fetchColumn() ?: 0);
if ($by === 0) { fwrite(STDERR, "No such active super-admin.\n"); exit(1); }

$raw = 'appm_' . bin2hex(random_bytes(24));
$pdo->beginTransaction();
try {
    $pdo->prepare('UPDATE application_model_credentials SET revoked_at = now() WHERE application_id = :a AND revoked_at IS NULL')->execute(['a' => $a['id']]);
    $st = $pdo->prepare('INSERT INTO application_model_credentials (application_id, label, token_hash, allowed_model_ids, monthly_budget_amount, acting_member_id)
                         VALUES (:a, :l, :h, :m::bigint[], :b, :by) RETURNING id');
    $st->execute(['a' => $a['id'], 'l' => (string) ($o['label'] ?? $a['name'] . ' (model credential)'), 'h' => hash('sha256', $raw),
        'm' => '{' . implode(',', array_map('intval', array_keys($found))) . '}', 'b' => $budget, 'by' => $by]);
    $id = (int) $st->fetchColumn();
    $pdo->commit();
} catch (Throwable $e) { $pdo->rollBack(); throw $e; }
log_activity($pdo, 'application.model_credential_mint', 'application', (int) $a['id'],
    ['source' => 'cron', 'actor_member_id' => $by, 'after' => ['credential_id' => $id, 'models' => array_values($found), 'monthly_budget' => $budget]]);
echo "Minted credential #{$id} for {$a['name']} (models: " . implode(', ', array_values($found)) . '; budget ' . ($budget ?? 'none') . ").\n";
echo "Shown once — set it as the engine's provider API key, pointed at the ledger proxy:\n{$raw}\n";
