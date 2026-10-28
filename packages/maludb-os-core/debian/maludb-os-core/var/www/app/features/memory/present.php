<?php
declare(strict_types=1);

/** Whitelist presenters for the Memory screens — the contract with web/lib/schemas/memory.ts. */

/**
 * One recalled memory. `from` is a name a person reads — never the namespace. The similarity is
 * deliberately absent: with no embedding model configured it is arbitrary
 * (docs/build-specs/agent-memory.md, "Known limit").
 */
function present_memory_result(array $r, array $labels): array
{
    $namespace = (string) ($r['namespace'] ?? '');
    return [
        'text' => (string) ($r['source_text'] ?? ''),
        'about' => ($r['subject_name'] ?? '') !== '' ? (string) $r['subject_name'] : null,
        'from' => $labels[$namespace] ?? 'shared memory',
        'from_kind' => $namespace === 'org' ? 'org' : (str_starts_with($namespace, 'dept:') ? 'department' : 'self'),
        'department_id' => preg_match('/^dept:(\d+)$/', $namespace, $m) === 1 ? (int) $m[1] : null,
    ];
}

function present_core_entry(string $key, array $entry): array
{
    $value = $entry['value'] ?? '';
    return [
        'key' => $key,
        'value' => is_scalar($value) ? (string) $value : (string) json_encode($value),
        'note' => ($entry['note'] ?? '') !== '' ? (string) $entry['note'] : null,
        'updated_at' => json_ts($entry['updated_at'] ?? null),
    ];
}

function present_memory_agent_link(array $a): array
{
    return [
        'member_id' => (int) $a['agent_member_id'],
        'name' => (string) $a['display_name'],
        'job_title' => ($a['job_title'] ?? '') !== '' ? (string) $a['job_title'] : null,
    ];
}
