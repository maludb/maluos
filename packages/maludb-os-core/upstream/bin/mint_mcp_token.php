<?php
declare(strict_types=1);

/**
 * Mint an access token for a member (until the Settings screen ships it).
 *   php bin/mint_mcp_token.php --email you@example.com --label "Claude Desktop"
 *   php bin/mint_mcp_token.php --email you@example.com --label "api-test" --scope api
 * Prints the raw token ONCE. --scope defaults to 'mcp' (the member's own AI connecting to
 * the read MCP endpoints, …/mcp/records, …/mcp/activity) or 'api' (the public JSON API,
 * /api/v1/…) — the two are different surfaces with different blast radii (db/078,
 * docs/build-specs/public-api-org-graph.md): an mcp-scoped token must not authenticate the
 * API and vice versa, so one revocation never has to mean both.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';

$opts = getopt('', ['email:', 'label:', 'scope:']);
$email = isset($opts['email']) ? normalize_email((string) $opts['email']) : '';
$label = trim((string) ($opts['label'] ?? 'Personal token'));
$scope = trim((string) ($opts['scope'] ?? 'mcp'));
if ($email === '') {
    fwrite(STDERR, "Usage: php bin/mint_mcp_token.php --email you@example.com [--label \"Claude Desktop\"] [--scope mcp|api]\n");
    exit(1);
}
if (!in_array($scope, ['mcp', 'api'], true)) {
    fwrite(STDERR, "--scope must be 'mcp' or 'api'.\n");
    exit(1);
}
$pdo = db();
$member = find_member_by_email($pdo, $email);
if ($member === null) { fwrite(STDERR, "No member for {$email}.\n"); exit(1); }

$raw = 'mcp_' . bin2hex(random_bytes(24));
$pdo->prepare('INSERT INTO mcp_access_tokens (member_id, label, token_hash, scope) VALUES (:m, :l, :h, :s)')
    ->execute(['m' => (int) $member['id'], 'l' => $label, 'h' => hash('sha256', $raw), 's' => $scope]);
log_activity($pdo, 'token.create', 'mcp_access_token', null, ['source' => 'cron', 'after' => ['member' => $email, 'label' => $label, 'scope' => $scope]]);

echo "{$scope} access token for {$email} (\"{$label}\") — shown once:\n\n  {$raw}\n\n";
if ($scope === 'api') {
    echo "Call the API with it (Bearer auth):\n";
    echo "  " . app_url('/api/v1/me') . "\n";
} else {
    echo "Connect a client to (Bearer auth):\n";
    echo "  " . app_url('/mcp/records') . "\n  " . app_url('/mcp/activity') . "\n";
}
