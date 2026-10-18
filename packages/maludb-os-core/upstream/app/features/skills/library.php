<?php
declare(strict_types=1);

/**
 * The skill library as people maintain it (AI Ops → Skills, 2026-09-27; docs/build-specs/skill-library.md).
 *
 * Skill text lives in the tenant's MaluDB; the kernel keeps only who holds which skill
 * (skill_assignments) and what agents proposed (skill_proposals). A skill is a bundle — SKILL.md
 * plus up to twenty text reference files — and a bundle is never edited: saving a changed one
 * ingests a NEW version (lineage kept, the previous version stays), and an unchanged one is a no-op.
 * An agent gets the newest ENABLED version of each skill it holds, unless its assignment pins one.
 * Saving here passes the same scan as an import or an agent's proposal (scan.php).
 */
require_once __DIR__ . '/maludb.php';
require_once __DIR__ . '/scan.php';
require_once __DIR__ . '/import.php';

/** Every version of every skill MaluDB holds, newest first per name. */
const SKILL_KINDS = ['skill' => 'Skill', 'runbook' => 'Runbook'];

/** A frontmatter kind, normalised: skill unless it says runbook; anything else is refused by the scan. */
function skill_kind_from_frontmatter(array $front): string
{
    return strtolower(trim((string) ($front['kind'] ?? ''))) === 'runbook' ? 'runbook' : 'skill';
}

/** Record a skill's kind by name (db/153) — on every ingest, so the list can say it without reading the bundle. */
function skill_kind_record(PDO $pdo, string $name, string $kind): void
{
    $st = $pdo->prepare('INSERT INTO skill_kinds (skill_name, kind, updated_at) VALUES (:n, :k, now())
                         ON CONFLICT (skill_name) DO UPDATE SET kind = EXCLUDED.kind, updated_at = now()');
    $st->execute(['n' => $name, 'k' => $kind]);
}

/** Every recorded kind: [name => kind]. */
function skill_kinds(PDO $pdo): array
{
    return $pdo->query('SELECT skill_name, kind FROM skill_kinds')->fetchAll(PDO::FETCH_KEY_PAIR);
}

/**
 * A skill's kind, from the record — or, for a skill ingested before db/153, from its bundle's
 * frontmatter once (one detail read per unknown name, then recorded). Unknown to MaluDB → skill.
 */
function skill_kind_of(PDO $pdo, string $name, ?int $skillId = null): string
{
    $st = $pdo->prepare('SELECT kind FROM skill_kinds WHERE skill_name = :n');
    $st->execute(['n' => $name]);
    if (($kind = $st->fetchColumn()) !== false) {
        return (string) $kind;
    }
    $kind = 'skill';
    try {
        if ($skillId !== null) {
            $detail = maludb_request('GET', '/v1/skills/' . $skillId);
            if ($detail['status'] === 200) {
                $kind = skill_kind_from_frontmatter(skill_frontmatter((string) ($detail['body']['skill']['markdown'] ?? '')));
            }
        }
        skill_kind_record($pdo, $name, $kind);
    } catch (Throwable) {
        // The list still answers; the kind stays "skill" until the bundle can be read.
    }
    return $kind;
}

function skill_library_rows(): array
{
    $rows = [];
    for ($offset = 0; ; $offset += 200) {                   // the API answers at most 200 a page
        $r = maludb_request('GET', '/v1/skills?limit=200&offset=' . $offset);
        if ($r['status'] !== 200) {
            throw new RuntimeException(maludb_error($r));
        }
        $page = $r['body']['skills'] ?? [];
        $rows = array_merge($rows, $page);
        if (count($page) < 200) {
            break;
        }
    }
    usort($rows, static fn (array $a, array $b): int => [$a['name'], $b['created_at']] <=> [$b['name'], $a['created_at']]);
    return $rows;
}

/** Live assignments per skill name: [name => count]. */
function skill_assignment_counts(PDO $pdo): array
{
    return $pdo->query('SELECT skill_name, count(*) FROM skill_assignments WHERE revoked_at IS NULL GROUP BY skill_name')
        ->fetchAll(PDO::FETCH_KEY_PAIR);
}

/**
 * The library as cards: one per skill name — the version an agent would get (the newest enabled),
 * how many versions exist, whether any is enabled, and how many live assignments hold it.
 */
function skill_library(PDO $pdo): array
{
    $counts = skill_assignment_counts($pdo);
    $by = [];
    foreach (skill_library_rows() as $row) {
        $name = (string) $row['name'];
        $by[$name]['name'] = $name;
        $by[$name]['versions'][] = $row;
    }
    $out = [];
    $kinds = skill_kinds($pdo);
    foreach ($by as $name => $s) {
        $enabled = array_values(array_filter($s['versions'], static fn (array $v): bool => !empty($v['enabled'])));
        $current = $enabled[0] ?? $s['versions'][0];
        $out[] = [
            'name' => $name,
            'kind' => $kinds[$name] ?? skill_kind_of($pdo, $name, (int) $current['id']),
            'description' => (string) ($current['description'] ?? ''),
            'current' => $current,
            'enabled' => $enabled !== [],
            'version_count' => count($s['versions']),
            'assignment_count' => (int) ($counts[$name] ?? 0),
        ];
    }
    return $out;
}

/** One skill: every version, the chosen one's SKILL.md and files, and who holds it. Null when unknown. */
function skill_library_get(PDO $pdo, string $name, ?int $versionId = null): ?array
{
    $versions = array_values(array_filter(skill_library_rows(), static fn (array $r): bool => $r['name'] === $name));
    if ($versions === []) {
        return null;
    }
    $enabled = array_values(array_filter($versions, static fn (array $v): bool => !empty($v['enabled'])));
    $chosen = $enabled[0] ?? $versions[0];
    if ($versionId !== null) {
        foreach ($versions as $v) {
            if ((int) $v['id'] === $versionId) {
                $chosen = $v;
            }
        }
    }
    $detail = maludb_request('GET', '/v1/skills/' . (int) $chosen['id']);
    $files = maludb_request('GET', '/v1/skills/' . (int) $chosen['id'] . '/files');
    if ($detail['status'] !== 200 || $files['status'] !== 200) {
        throw new RuntimeException(maludb_error($detail['status'] !== 200 ? $detail : $files));
    }
    $contents = [];
    foreach ($files['body']['files'] ?? [] as $f) {
        $path = (string) $f['relative_path'];
        if ($path === 'SKILL.md') {
            continue;
        }
        $text = maludb_skill_file_text((int) $chosen['id'], $path);
        $contents[] = ['path' => $path, 'size' => (int) ($f['file_size'] ?? 0), 'content' => $text];
    }
    require_once __DIR__ . '/queries.php';
    $held = array_values(array_filter(list_skill_assignments($pdo), static fn (array $a): bool => $a['skill_name'] === $name));
    return [
        'name' => $name,
        'versions' => $versions,
        'chosen' => $chosen,
        'current_id' => (int) (($enabled[0] ?? $versions[0])['id']),
        'markdown' => (string) ($detail['body']['skill']['markdown'] ?? ''),
        'kind' => skill_kind_from_frontmatter(skill_frontmatter((string) ($detail['body']['skill']['markdown'] ?? ''))),
        'bundle_hash' => (string) ($files['body']['bundle_hash'] ?? ''),
        'files' => $contents,
        'assignments' => $held,
    ];
}

/**
 * SKILL.md from the form's parts: the frontmatter the library reads (name, description — one line
 * each) and the body as written.
 */
function skill_compose_markdown(string $name, string $description, string $body, string $kind = 'skill'): string
{
    return "---\nname: {$name}\ndescription: " . str_replace(["\r", "\n"], ' ', $description) . ($kind === 'runbook' ? "\nkind: runbook" : '') . "\n---\n\n" . ltrim($body) . "\n";
}

/** The body of a SKILL.md — what follows its frontmatter. */
function skill_markdown_body(string $markdown): string
{
    return preg_match('/\A---\R.*?\R---\R(.*)\z/s', $markdown, $m) ? ltrim($m[1]) : $markdown;
}

/**
 * Save a skill from the form: a new skill, or a new version of one. Answers [ingested, errors,
 * findings]; ingested carries skill_id, bundle_hash, reused (nothing changed), name.
 *
 * @param array<int,array{relative_path:string,content:string}> $files reference files besides SKILL.md
 */
function skill_library_save(PDO $pdo, string $name, string $description, string $body, array $files, string $kind = 'skill'): array
{
    $errors = [];
    if (!isset(SKILL_KINDS[$kind])) {
        $errors[] = 'A skill is a skill or a runbook.';
    }
    if (!preg_match(SKILL_NAME_PATTERN, $name)) {
        $errors[] = 'A skill name is lower-case letters, digits and hyphens (2–64), starting with a letter or digit.';
    }
    $description = trim(preg_replace('/\s+/', ' ', $description) ?? '');
    if ($description === '' || mb_strlen($description) > 1024) {
        $errors[] = 'A skill needs a description (up to 1,024 characters) — it is how an agent knows when to use it.';
    }
    if (trim($body) === '') {
        $errors[] = 'A skill needs its instructions.';
    }
    $seen = [];
    foreach ($files as $f) {
        $p = (string) $f['relative_path'];
        if ($p === '' || strtolower($p) === 'skill.md' || isset($seen[$p])) {
            $errors[] = 'Each reference file needs its own path, and SKILL.md is the instructions above: ' . ($p ?: '(no path)') . '.';
        }
        $seen[$p] = true;
    }
    if ($errors !== []) {
        return [null, $errors, []];
    }
    $markdown = skill_compose_markdown($name, $description, $body, $kind);
    $bundle = array_merge([['relative_path' => 'SKILL.md', 'content' => $markdown]], $files);
    usort($bundle, static fn (array $a, array $b): int => strcmp($a['relative_path'], $b['relative_path']));
    [$refusal, $findings] = scan_skill_bundle($name, $bundle);
    if ($refusal !== null) {
        return [null, ['Refused: ' . $refusal], $findings];
    }
    [$ingested, $error] = maludb_skill_ingest($name, $description, $markdown, $bundle);
    if ($error !== null) {
        return [null, [$error], $findings];
    }
    skill_kind_record($pdo, $name, $kind);
    return [$ingested + ['name' => $name], [], $findings];
}
