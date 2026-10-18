<?php
declare(strict_types=1);

/**
 * Bootstrap the first SUPER-ADMIN. Invite-only registration has a chicken-and-egg problem:
 * nobody can send the first invite until an administrator exists. Run this once per install,
 * after the migrations (docs/install.md).
 *
 *   php bin/bootstrap_organizer.php --email you@example.com --name "Your Name" [--password secret]
 *
 * The member it creates is a super-admin (business_role, db/051) — the only role admitted to the
 * os.<domain> face, the one that decides approvals and grants application access. Before
 * 2026-10-06 it created an 'organizer' with the default business role 'user', which on a fresh
 * installation locked everyone out of the OS (member #1 was promoted by db/051 only where it
 * already existed). If --password is omitted, a strong random password is generated and printed
 * once. Refuses if a member with that email already exists.
 */

if (PHP_SAPI !== 'cli') {
    fwrite(STDERR, "CLI only.\n");
    exit(1);
}

require_once dirname(__DIR__) . '/app/bootstrap.php';

$opts = getopt('', ['email:', 'name:', 'password:']);
$email = isset($opts['email']) ? normalize_email((string) $opts['email']) : '';
$name  = trim((string) ($opts['name'] ?? ''));
$password = (string) ($opts['password'] ?? '');

if ($email === '' || $name === '') {
    fwrite(STDERR, "Usage: php bin/bootstrap_organizer.php --email you@example.com --name \"Your Name\" [--password secret]\n");
    exit(1);
}
if (filter_var($email, FILTER_VALIDATE_EMAIL) === false) {
    fwrite(STDERR, "Invalid email.\n");
    exit(1);
}

$generated = false;
if ($password === '') {
    $password = bin2hex(random_bytes(9));   // 18 hex chars
    $generated = true;
}
$pwErrors = validate_password($password);
if ($pwErrors !== []) {
    fwrite(STDERR, implode("\n", $pwErrors) . "\n");
    exit(1);
}

$pdo = db();
if (find_member_by_email($pdo, $email) !== null) {
    fwrite(STDERR, "A member already exists for {$email}.\n");
    exit(1);
}

$st = $pdo->prepare(<<<'SQL'
    INSERT INTO members (email, password_hash, display_name, role, business_role, email_verified_at)
    VALUES (:e, :h, :n, 'organizer', 'super_admin', now())
    RETURNING id
SQL);
$st->execute(['e' => $email, 'h' => hash_password($password), 'n' => $name]);
$id = (int) $st->fetchColumn();

log_activity($pdo, 'member.bootstrap_organizer', 'member', $id, ['source' => 'cron', 'after' => ['email' => $email]]);

echo "Created super-admin #{$id}: {$name} <{$email}>\n";
if ($generated) {
    echo "Generated password (store it now, shown once): {$password}\n";
}
echo "Log in at " . app_url('/login') . "\n";
