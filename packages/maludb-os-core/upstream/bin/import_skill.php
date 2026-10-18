<?php
declare(strict_types=1);

/**
 * Put a skill folder into MaluDB, enabled — how a person seeds the skill library.
 *   php bin/import_skill.php --dir /path/to/file-a-vendor-bill --email you@example.com
 * The folder holds SKILL.md (frontmatter `name:` and `description:`) and optional text reference
 * files. It passes the SAME scan an agent-written skill does: text only, no scripts, in v1 — a
 * skill is instructions every agent that receives it will follow. A changed folder becomes a new
 * version with lineage; an unchanged one is a no-op. Importing assigns it to nobody: that is
 * skill_assign, a separate and deliberate act.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/skills/import.php';
$opts = getopt('', ['dir:', 'email:']);
$dir = rtrim((string) ($opts['dir'] ?? ''), '/');
$email = isset($opts['email']) ? normalize_email((string) $opts['email']) : '';
if ($dir === '' || !is_file($dir . '/SKILL.md') || $email === '') {
    fwrite(STDERR, "Usage: php bin/import_skill.php --dir <folder holding SKILL.md> --email <the importing admin>\n");
    exit(1);
}
$pdo = db();
$member = find_member_by_email($pdo, $email);
if ($member === null || ($member['business_role'] ?? '') !== 'super_admin') {
    fwrite(STDERR, "Importing a skill is for a super-admin.\n");
    exit(1);
}
$_SESSION['member_id'] = (int) $member['id'];
[$ingested, $error, $findings] = import_skill_folder($pdo, $dir, (int) $member['id']);
foreach ($findings as $f) {
    fwrite(STDERR, "note: {$f['kind']} in {$f['file']}: {$f['detail']}\n");
}
if ($error !== null) {
    fwrite(STDERR, $error . "\n");
    exit(1);
}
echo ($ingested['reused'] ? 'Unchanged' : 'Imported') . ": {$ingested['name']}  id={$ingested['skill_id']}  hash=" . substr($ingested['bundle_hash'], 0, 12) . "\n";
