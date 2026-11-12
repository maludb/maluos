<?php
declare(strict_types=1);

/**
 * The public names of the kernel's applications and where each one runs (db/194): one line per active
 * application, "<name>\t<address>", the address being the application server's (locations.node_address) or
 * "kernel" for one beside the kernel. For the proxy's upstreams and the office's hosts block (MaluOS:
 * maluctl app names --upstreams). Read-only.
 *   php bin/app_names.php [--json]
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
$pdo = db();
$admin = (int) $pdo->query("SELECT id FROM members WHERE business_role = 'super_admin' AND status = 'active' AND member_kind = 'human' ORDER BY id LIMIT 1")->fetchColumn();
$_SESSION['member_id'] = $admin;
db_apply_context($pdo);
$rows = $pdo->query(<<<'SQL'
    SELECT a.app_key, a.url, a.internal_base_url, l.name AS node, l.node_address
    FROM applications a LEFT JOIN locations l ON l.id = a.location_id AND a.internal_base_url IS NOT NULL
    WHERE a.status IN ('active', 'degraded') AND a.catalog_key IS NOT NULL AND a.url IS NOT NULL
    ORDER BY a.app_key
SQL)->fetchAll();
$out = [];
foreach ($rows as $r) {
    $host = (string) (parse_url((string) $r['url'], PHP_URL_HOST) ?: '');
    if ($host === '') { continue; }
    $out[] = ['key' => (string) $r['app_key'], 'name' => $host, 'address' => $r['internal_base_url'] !== null ? (string) ($r['node_address'] ?? '') : 'kernel',
              'node' => $r['internal_base_url'] !== null ? (string) ($r['node'] ?? '') : null];
}
if (in_array('--json', $argv, true)) { echo json_encode($out, JSON_UNESCAPED_SLASHES) . "\n"; exit(0); }
foreach ($out as $o) { echo $o['name'] . "\t" . ($o['address'] !== '' ? $o['address'] : '?') . "\n"; }
