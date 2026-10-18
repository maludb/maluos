<?php
declare(strict_types=1);

/**
 * What a skill bundle may contain, and what a reviewer should look at
 * (docs/build-specs/agent-skills.md, "Up-sync"). A skill is instructions every agent that receives
 * it will follow, so an agent-written one is the obvious carrier for a prompt injection: a poisoned
 * document talks one agent into "learning" something, and the skill spreads it. REFUSALS are
 * structural — things no v1 skill may be. FINDINGS never refuse; they point the reviewer's eye.
 */

const SKILL_MAX_FILES = 20;
const SKILL_MAX_BYTES = 262144;
const SKILL_TEXT_EXTENSIONS = ['md', 'markdown', 'txt', 'json', 'yaml', 'yml', 'csv'];
const SKILL_NAME_PATTERN = '/^[a-z0-9][a-z0-9\-]{1,63}$/';

/** @return array{name:?string, description:?string} the two frontmatter fields the platform reads */
function skill_frontmatter(string $markdown): array
{
    $out = ['name' => null, 'description' => null, 'kind' => null];   // kind: skill (default) or runbook (db/153)
    if (!preg_match('/\A---\R(.*?)\R---\R/s', $markdown, $m)) {
        return $out;
    }
    $lines = preg_split('/\R/', $m[1]);
    foreach ($lines as $i => $line) {
        if (!preg_match('/^(name|description|kind):\s*(.*?)\s*$/', $line, $kv)) {
            continue;
        }
        $value = $kv[2];
        // A YAML block (`>` folded, `|` literal, with an optional chomping sign): the indented lines below.
        if (preg_match('/^[>|][+-]?$/', $value)) {
            $block = [];
            for ($j = $i + 1; $j < count($lines) && ($lines[$j] === '' || preg_match('/^\s+\S/', $lines[$j])); $j++) {
                $block[] = trim($lines[$j]);
            }
            $value = $value[0] === '>' ? trim(preg_replace('/\s+/', ' ', implode(' ', $block)) ?? '') : trim(implode("\n", $block));
        }
        $out[$kv[1]] = trim($value, "\"' ");
    }
    return $out;
}

/**
 * @param array<int,array{relative_path:string,content:string}> $files
 * @return array{0:?string,1:array<int,array{kind:string,file:string,detail:string}>} [refusal, findings]
 */
function scan_skill_bundle(string $name, array $files): array
{
    if (!preg_match(SKILL_NAME_PATTERN, $name)) {
        return ['A skill name is lower-case letters, digits and hyphens (2–64).', []];
    }
    if ($files === [] || count($files) > SKILL_MAX_FILES) {
        return ['A skill bundle holds between 1 and ' . SKILL_MAX_FILES . ' files.', []];
    }
    $paths = array_column($files, 'relative_path');
    if (!in_array('SKILL.md', $paths, true)) {
        return ['A skill bundle must contain SKILL.md.', []];
    }
    $total = 0;
    $findings = [];
    foreach ($files as $f) {
        $path = $f['relative_path'];
        $total += strlen($f['content']);
        if ($path === '' || $path[0] === '/' || str_contains($path, '\\') || in_array('..', explode('/', $path), true)
            || !preg_match('#^[A-Za-z0-9_.\-/ ]+$#', $path)) {
            return ['"' . $path . '" is not a path inside the skill.', []];
        }
        $ext = strtolower(pathinfo($path, PATHINFO_EXTENSION));
        if (!in_array($ext, SKILL_TEXT_EXTENSIONS, true)) {
            return ['"' . $path . '": a skill written by an agent may hold text files only ('
                . implode(', ', SKILL_TEXT_EXTENSIONS) . ') — no scripts, no binaries.', []];
        }
        if (!mb_check_encoding($f['content'], 'UTF-8') || str_contains($f['content'], "\0") || str_starts_with($f['content'], '#!')) {
            return ['"' . $path . '" is not plain text.', []];
        }
        foreach ([
            'url' => '#https?://[^\s)>\]]+#i',
            'shell' => '/^\s*(?:\$ |sudo |curl |wget |rm -|chmod |bash |sh -c|pip install|npm install)/mi',
            'addresses_the_reader_as_a_system' => '/ignore (?:all |any )?(?:previous|prior|above)|disregard (?:your|the) (?:instructions|rules)|you must always|never tell|do not (?:tell|inform|mention)[^.\n]{0,40}(?:manager|user|human)|system prompt|without (?:asking|approval|checking)/i',
            'credentials' => '/(?:api[_ -]?key|password|secret|token)\s*[:=]/i',
        ] as $kind => $pattern) {
            if (preg_match_all($pattern, $f['content'], $hits)) {
                $findings[] = ['kind' => $kind, 'file' => $path, 'detail' => mb_substr(trim($hits[0][0]), 0, 120)
                    . (count($hits[0]) > 1 ? ' (+' . (count($hits[0]) - 1) . ' more)' : '')];
            }
        }
    }
    if ($total > SKILL_MAX_BYTES) {
        return ['The bundle is larger than ' . intdiv(SKILL_MAX_BYTES, 1024) . ' KB.', []];
    }
    return [null, $findings];
}
