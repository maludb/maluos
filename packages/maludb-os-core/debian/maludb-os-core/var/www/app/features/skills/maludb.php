<?php
declare(strict_types=1);

/**
 * MaluDB's skill routes, as the platform uses them (docs/build-specs/agent-skills.md). Builds on
 * the one PHP client (features/memory/maludb.php): same token, same rule — nothing but PHP, the
 * Memory server and the runner ever holds it.
 */
require_once dirname(__DIR__) . '/memory/maludb.php';

/**
 * Ingest a bundle. ALWAYS as materially different: MaluDB otherwise treats a whitespace-only change
 * as superseding and DISABLES the parent — and a proposal is ingested disabled, so the live skill
 * would vanish until someone decided. With this flag both versions coexist.
 * @param array<int,array{relative_path:string,content:string}> $files
 * @return array{0:?array,1:?string} [{skill_id, bundle_hash, reused, parent_skill_id}, error]
 */
function maludb_skill_ingest(string $name, string $description, string $markdown, array $files, string $kind = 'skill'): array
{
    $r = maludb_request('POST', '/v1/skills/ingest', [
        'name' => $name, 'description' => $description, 'markdown' => $markdown,
        'frontmatter' => ['name' => $name, 'description' => $description, 'kind' => $kind],
        'materially_different' => true,
        'files' => array_map(static fn (array $f): array => [
            'relative_path' => $f['relative_path'], 'content_base64' => base64_encode($f['content']),
        ], $files),
    ]);
    if ($r['status'] !== 201 && $r['status'] !== 200) {
        return [null, maludb_error($r)];
    }
    return [[
        'skill_id' => (int) ($r['body']['skill_id'] ?? 0), 'bundle_hash' => (string) ($r['body']['bundle_hash'] ?? ''),
        'reused' => (bool) ($r['body']['reused'] ?? false),
        'parent_skill_id' => isset($r['body']['parent']['skill_id']) ? (int) $r['body']['parent']['skill_id'] : null,
    ], null];
}

function maludb_skill_set_enabled(int $skillId, bool $enabled): ?string
{
    $r = maludb_request('PATCH', '/v1/skills/' . $skillId, ['enabled' => $enabled]);
    return $r['status'] === 200 ? null : maludb_error($r);
}

/** @return array{0:?array,1:?string} [skill row, error]; a 404 is [null, null] — "no such skill" is an answer */
function maludb_skill_resolve(string $name, ?string $bundleHash = null): array
{
    $query = http_build_query(array_filter(['name' => $name, 'bundle_hash' => $bundleHash], static fn ($v) => $v !== null && $v !== ''));
    $r = maludb_request('GET', '/v1/skills/resolve?' . $query);
    if ($r['status'] === 404) {
        return [null, null];
    }
    return $r['status'] === 200 ? [$r['body']['skill'] ?? null, null] : [null, maludb_error($r)];
}

function maludb_skill_file_text(int $skillId, string $path): ?string
{
    $r = maludb_request('GET', '/v1/skills/' . $skillId . '/files/' . implode('/', array_map('rawurlencode', explode('/', $path))));
    return $r['status'] === 200 ? ($r['body']['file']['text'] ?? null) : null;
}
