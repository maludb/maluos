<?php
declare(strict_types=1);

/**
 * Mint a one-time desk enrolment code for a person (db/187; the Settings → Desks screen does the same
 * for oneself). Prints the code ONCE with its expiry; the desk runs
 *   sudo maluctl office enroll https://app.<domain> --code XXXX-XXXX
 * within fifteen minutes.
 *   php bin/mint_desk_code.php --email you@example.com [--name "Ed's desk"]
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/estate/desks.php';

$opts = getopt('', ['email:', 'name:']);
$email = isset($opts['email']) ? normalize_email((string) $opts['email']) : '';
if ($email === '') {
    fwrite(STDERR, "Usage: php bin/mint_desk_code.php --email you@example.com [--name \"Ed's desk\"]\n");
    exit(1);
}
$pdo = db();
$member = find_member_by_email($pdo, $email);
if ($member === null || $member['status'] !== 'active') { fwrite(STDERR, "No active member for {$email}.\n"); exit(1); }
if (($member['member_kind'] ?? 'human') !== 'human' || !empty($member['is_external'])) { fwrite(STDERR, "{$email} cannot own a desk (an agent or an external).\n"); exit(1); }
$c = desk_code_mint($pdo, (int) $member['id'], trim((string) ($opts['name'] ?? '')), (int) $member['id']);
log_activity($pdo, 'desk.code.mint', 'desk_enrollment_code', $c['id'], ['source' => 'cron', 'after' => ['member' => $email, 'desk_name' => $opts['name'] ?? null]]);
echo "Desk enrolment code for {$email} — shown once, valid until {$c['expires_at']}:\n\n  {$c['code']}\n\n";
echo "On the MaluOS desktop:\n  sudo maluctl office enroll " . app_url('/') . " --code {$c['code']}\n";
