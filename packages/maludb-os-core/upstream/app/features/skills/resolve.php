<?php
declare(strict_types=1);

/**
 * The skills an agent will carry into its next run — resolved here exactly as the runner resolves
 * them before every run (mcp/agent_runner/skills.py choose() over store.skill_assignments_for()):
 * every live assignment that reaches the agent (itself, its role, its departments, the applications
 * it may use or is the expert on, the organisation), the most specific one per name winning, and
 * runtime_config.pinned_skills overriding all. What the tab shows is what the run gets.
 *
 * Delivery depends on the harness (docs/build-specs/agent-skills.md): the Claude harness inlines the
 * first SKILLS_MAX skills, by name, at SKILL_CHARS each, and the rest are reachable through the
 * skill_read tool; Hermes reads the whole synced folder; a system_one agent uses none.
 */
require_once __DIR__ . '/queries.php';
require_once __DIR__ . '/maludb.php';
require_once __DIR__ . '/library.php';

const SKILL_SPECIFICITY = ['agent' => 0, 'role' => 1, 'department' => 2, 'application' => 3, 'org' => 4];
const SKILL_INLINE_MAX = 12;       // claude_render.py SKILLS_MAX
const SKILL_INLINE_CHARS = 6000;   // claude_render.py SKILL_CHARS

/** Every live assignment reaching the agent, with the names the tab shows. */
function skill_assignments_reaching(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT a.*, d.name AS department_name, ap.name AS application_name, by_m.display_name AS assigned_by_name,
               coalesce(k.kind, 'skill') AS kind
          FROM skill_assignments a
          LEFT JOIN skill_kinds k ON k.skill_name = a.skill_name
          LEFT JOIN departments d ON d.id = a.department_id
          LEFT JOIN applications ap ON ap.id = a.application_id
          LEFT JOIN members by_m ON by_m.id = a.assigned_by
         WHERE a.revoked_at IS NULL
           AND (a.scope_kind = 'org'
             OR (a.scope_kind = 'department' AND a.department_id IN (SELECT dm.department_id FROM department_members dm WHERE dm.member_id = :m1 AND dm.left_at IS NULL))
             OR (a.scope_kind = 'role' AND a.role_key = (SELECT p.role_key FROM agent_profiles p WHERE p.member_id = :m2))
             OR (a.scope_kind = 'agent' AND a.agent_member_id = :m3)
             OR (a.scope_kind = 'application' AND a.application_id = ANY (app_agent_skill_application_ids(:m4))))
         ORDER BY a.skill_name, a.id
    SQL);
    $st->execute(['m1' => $memberId, 'm2' => $memberId, 'm3' => $memberId, 'm4' => $memberId]);
    return $st->fetchAll();
}

/** Where an assignment comes from, as the tab says it: a label, and the record it links to. */
function skill_source_of(array $a): array
{
    return match ($a['scope_kind']) {
        'agent' => ['scope_kind' => 'agent', 'label' => 'This agent', 'href' => null],
        'role' => ['scope_kind' => 'role', 'label' => 'Role ' . (string) $a['role_key'], 'href' => null],
        'department' => ['scope_kind' => 'department', 'label' => (string) ($a['department_name'] ?? ('department #' . $a['department_id'])),
                         'href' => '/team/departments/' . (int) $a['department_id']],
        'application' => ['scope_kind' => 'application', 'label' => (string) ($a['application_name'] ?? ('application #' . $a['application_id'])),
                          'href' => '/applications/' . (int) $a['application_id']],
        default => ['scope_kind' => 'org', 'label' => 'Everyone', 'href' => null],
    };
}

/**
 * @param array $agent   the mcp_agents row (agent_member_id, harness)
 * @param array $runtime the current version's runtime_config (pinned_skills)
 */
function resolve_agent_skills(PDO $pdo, array $agent, array $runtime): array
{
    $memberId = (int) $agent['agent_member_id'];
    $harness = (string) ($agent['harness'] ?? '');
    $rule = match ($harness) { 'claude_agent_sdk' => 'inline', 'hermes' => 'folder', default => 'none' };

    // The library, for descriptions, versions and what is enabled. Unreachable → the tab still shows the assignments.
    $library = [];
    $libraryError = null;
    try {
        foreach (skill_library_rows() as $row) {
            $name = (string) $row['name'];
            if (!isset($library[$name]) || (!empty($row['enabled']) && empty($library[$name]['enabled']))) {
                $library[$name] = $row;   // rows arrive newest first per name: the first enabled one is what a run gets
            }
        }
    } catch (Throwable $ex) {
        $libraryError = 'The skill library could not be read: ' . $ex->getMessage();
    }

    // choose(): the most specific live assignment of each name wins; the others are shadowed.
    $chosen = [];
    foreach (skill_assignments_reaching($pdo, $memberId) as $a) {
        $name = (string) $a['skill_name'];
        $rank = SKILL_SPECIFICITY[$a['scope_kind']] ?? 9;
        if (!isset($chosen[$name])) {
            $chosen[$name] = ['winner' => $a, 'rank' => $rank, 'shadowed' => []];
        } elseif ($rank < $chosen[$name]['rank']) {
            $chosen[$name]['shadowed'][] = $chosen[$name]['winner'];
            $chosen[$name] = ['winner' => $a, 'rank' => $rank, 'shadowed' => $chosen[$name]['shadowed']];
        } else {
            $chosen[$name]['shadowed'][] = $a;
        }
    }
    // runtime_config.pinned_skills overrides every assignment — and can add a skill nobody assigned.
    $pins = [];
    foreach ((array) ($runtime['pinned_skills'] ?? []) as $p) {
        if (is_array($p) && !empty($p['name'])) {
            $pins[(string) $p['name']] = isset($p['bundle_hash']) ? (string) $p['bundle_hash'] : null;
        }
    }
    foreach ($pins as $name => $hash) {
        if (!isset($chosen[$name])) {
            $chosen[$name] = ['winner' => null, 'rank' => -1, 'shadowed' => []];
        }
    }
    ksort($chosen);   // the runner syncs and inlines by name

    $out = [];
    $n = 0;
    foreach ($chosen as $name => $c) {
        $w = $c['winner'];
        $lib = $library[$name] ?? null;
        $pinnedHash = array_key_exists($name, $pins) ? $pins[$name] : ($w['pinned_bundle_hash'] ?? null);
        $delivery = match (true) {
            $rule === 'none' => 'none',
            $rule === 'folder' => 'folder',
            $n < SKILL_INLINE_MAX => 'inline',
            default => 'on_request',
        };
        $n++;
        $out[] = [
            'name' => $name,
            'kind' => $w !== null ? (string) ($w['kind'] ?? 'skill') : ($lib !== null ? skill_kind_of($pdo, $name, (int) $lib['id']) : 'skill'),
            'description' => $lib !== null ? (string) ($lib['description'] ?? '') : null,
            'in_library' => $lib !== null,
            'enabled' => $lib !== null ? !empty($lib['enabled']) : null,
            'version' => $lib !== null ? (string) ($lib['version'] ?? '') : null,
            'source' => $w !== null ? skill_source_of($w) : ['scope_kind' => 'pinned', 'label' => 'Pinned in the configuration', 'href' => null],
            'assignment_id' => $w !== null ? (int) $w['id'] : null,
            'assigned_by' => $w !== null && ($w['assigned_by'] ?? null) !== null ? ['id' => (int) $w['assigned_by'], 'name' => $w['assigned_by_name'] ?? null] : null,
            'note' => $w['note'] ?? null,
            'pinned_bundle_hash' => $pinnedHash,
            'pinned_by_config' => array_key_exists($name, $pins),
            'shadowed' => array_map('skill_source_of', $c['shadowed']),
            'delivery' => $delivery,
        ];
    }

    $resolvedNames = array_column($out, 'name');
    $assignable = [];
    $kinds = skill_kinds($pdo);
    foreach ($library as $name => $row) {
        if (!empty($row['enabled']) && !in_array($name, $resolvedNames, true)) {
            $assignable[] = ['name' => $name, 'kind' => $kinds[$name] ?? skill_kind_of($pdo, $name, (int) $row['id']), 'description' => (string) ($row['description'] ?? '')];
        }
    }
    usort($assignable, static fn (array $a, array $b): int => strcmp($a['name'], $b['name']));

    return [
        'harness' => $harness, 'rule' => $rule, 'inline_max' => SKILL_INLINE_MAX, 'inline_chars' => SKILL_INLINE_CHARS,
        'resolved' => $out, 'assignable' => $assignable, 'library_error' => $libraryError,
        'can' => ['assign' => can_assign_skill($pdo, 'agent', null, $memberId)],
    ];
}
