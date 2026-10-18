<?php
declare(strict_types=1);

/**
 * Put a skill folder into MaluDB, enabled — what bin/import_skill.php does for a person and
 * bin/hire_installation_agent.php does for the skills an agent ships with. The folder holds
 * SKILL.md (frontmatter `name:` and `description:`) and optional text reference files, and passes
 * the SAME scan an agent-written skill does. A changed folder becomes a new version with lineage;
 * an unchanged one is a no-op. Importing assigns it to nobody.
 *
 * @return array{0: ?array, 1: ?string, 2: array} [ingested (skill_id, bundle_hash, reused), error, findings]
 */
require_once __DIR__ . '/maludb.php';
require_once __DIR__ . '/library.php';
require_once __DIR__ . '/scan.php';

function import_skill_folder(PDO $pdo, string $dir, int $by): array
{
    $dir = rtrim($dir, '/');
    if (!is_file($dir . '/SKILL.md')) {
        return [null, "No SKILL.md in {$dir}.", []];
    }
    $files = [];
    $walk = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($dir, FilesystemIterator::SKIP_DOTS));
    foreach ($walk as $file) {
        if ($file->isFile()) {
            $files[] = ['relative_path' => ltrim(substr($file->getPathname(), strlen($dir)), '/'), 'content' => (string) file_get_contents($file->getPathname())];
        }
    }
    usort($files, static fn (array $a, array $b): int => strcmp($a['relative_path'], $b['relative_path']));
    $markdown = (string) file_get_contents($dir . '/SKILL.md');
    $front = skill_frontmatter($markdown);
    $name = (string) ($front['name'] ?? basename($dir));
    [$refusal, $findings] = scan_skill_bundle($name, $files);
    if ($refusal !== null || (string) ($front['description'] ?? '') === '') {
        return [null, 'Refused: ' . ($refusal ?? 'SKILL.md needs a frontmatter description.'), $findings];
    }
    $kind = skill_kind_from_frontmatter($front);   // a shipped runbook says `kind: runbook` (db/153)
    [$ingested, $error] = maludb_skill_ingest($name, (string) $front['description'], $markdown, $files, $kind);
    if ($error !== null) {
        return [null, $error, $findings];
    }
    skill_kind_record($pdo, $name, $kind);
    log_activity($pdo, 'skill.import', 'skill', $ingested['skill_id'], [
        'source' => PHP_SAPI === 'cli' ? 'cron' : 'web',
        'after' => ['skill_name' => $name, 'bundle_hash' => $ingested['bundle_hash'], 'files' => count($files), 'reused' => $ingested['reused']],
    ]);
    return [$ingested + ['name' => $name], null, $findings];
}
