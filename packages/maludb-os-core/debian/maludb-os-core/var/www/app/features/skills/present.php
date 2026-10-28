<?php
declare(strict_types=1);

/** JSON whitelists for skills. A proposal's two SKILL.md texts are only in the detail presenter. */

function present_skill_assignment(array $a): array
{
    return [
        'skill_assignment_id' => (int) $a['id'], 'skill_name' => $a['skill_name'], 'kind' => (string) ($a['kind'] ?? 'skill'),
        'pinned_bundle_hash' => $a['pinned_bundle_hash'], 'scope_kind' => $a['scope_kind'],
        'department' => $a['department_id'] !== null ? ['id' => (int) $a['department_id'], 'name' => $a['department_name'] ?? null] : null,
        'role_key' => $a['role_key'],
        'agent' => $a['agent_member_id'] !== null ? ['member_id' => (int) $a['agent_member_id'], 'name' => $a['agent_name'] ?? null] : null,
        'application' => ($a['application_id'] ?? null) !== null
            ? ['id' => (int) $a['application_id'], 'name' => $a['application_name'] ?? null] : null,
        'note' => $a['note'], 'assigned_by' => $a['assigned_by_name'] ?? null, 'assigned_by_member_id' => ($a['assigned_by'] ?? null) !== null ? (int) $a['assigned_by'] : null, 'created_at' => json_ts($a['created_at']),
    ];
}

function present_skill_proposal(array $p, bool $withTexts = false): array
{
    $out = [
        'skill_proposal_id' => (int) $p['id'], 'skill_name' => $p['skill_name'], 'status' => $p['status'],
        'agent' => ['member_id' => (int) $p['agent_member_id'], 'name' => $p['agent_name'] ?? null],
        'agent_run_id' => $p['agent_run_id'] !== null ? (int) $p['agent_run_id'] : null,
        'bundle_hash' => $p['bundle_hash'], 'parent_bundle_hash' => $p['parent_bundle_hash'],
        'is_change' => $p['parent_bundle_hash'] !== null, 'file_count' => (int) $p['file_count'],
        'scan_findings' => json_decode((string) $p['scan_findings'], true) ?: [],
        'decided_by' => $p['decided_by_name'] ?? null, 'decided_by_member_id' => ($p['decided_by'] ?? null) !== null ? (int) $p['decided_by'] : null, 'decided_at' => json_ts($p['decided_at']),
        'decision_note' => $p['decision_note'], 'created_at' => json_ts($p['created_at']),
    ];
    if ($withTexts) {
        $out['skill_markdown'] = $p['skill_markdown'];
        $out['parent_markdown'] = $p['parent_markdown'];
    }
    return $out;
}

// ---- the skill library (AI Ops → Skills, 2026-09-27) ---------------------------------------------

/** One version of a skill as MaluDB lists it. */
function present_skill_version(array $v): array
{
    return [
        'id' => (int) $v['id'],
        'version' => (string) ($v['version'] ?? ''),
        'enabled' => !empty($v['enabled']),
        'created_at' => (string) ($v['created_at'] ?? ''),
        'description' => (string) ($v['description'] ?? ''),
    ];
}

/** A skill as a card (skill_library()). */
function present_library_skill(array $s): array
{
    return [
        'name' => (string) $s['name'],
        'kind' => (string) ($s['kind'] ?? 'skill'),
        'description' => (string) $s['description'],
        'current' => present_skill_version($s['current']),
        'enabled' => (bool) $s['enabled'],
        'version_count' => (int) $s['version_count'],
        'assignment_count' => (int) $s['assignment_count'],
    ];
}

/** One skill in full (skill_library_get()). */
function present_library_skill_detail(array $s): array
{
    return [
        'name' => (string) $s['name'],
        'kind' => (string) ($s['kind'] ?? 'skill'),
        'versions' => array_map('present_skill_version', $s['versions']),
        'chosen' => present_skill_version($s['chosen']),
        'current_id' => (int) $s['current_id'],
        'markdown' => (string) $s['markdown'],
        'body' => skill_markdown_body((string) $s['markdown']),
        'bundle_hash' => (string) $s['bundle_hash'],
        'files' => array_map(static fn (array $f): array => ['path' => (string) $f['path'], 'size' => (int) $f['size'],
            'content' => $f['content'] !== null ? (string) $f['content'] : null], $s['files']),
        'assignments' => array_map('present_skill_assignment', $s['assignments']),
    ];
}
