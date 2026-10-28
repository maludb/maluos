<?php
declare(strict_types=1);

/**
 * The focused Agent View: the org-graph payload centred on a record instead of a person
 * (build spec: docs/build-specs/agent-view-focus-graph.md).
 *
 * THE RULE THAT DOES MOST OF THE WORK. A focused graph shows exactly what the focus record's
 * own screen already shows that viewer, as a picture — never more. So every builder below
 * (1) applies the gate its screen applies, (2) finds the record with the function its screen
 * finds it with, and (3) fills each ring with a list that screen already renders, read with the
 * query function that screen already calls. There is no SQL in this file and no visibility
 * decision: a second implementation is how a screen and a picture end up disagreeing. db/080's
 * masking arrives already applied, because the rows come from the same views.
 *
 * A refused gate and a missing record both answer NULL, which the endpoint maps to 404 — the
 * two are indistinguishable on purpose (spec "Errors").
 */
require_once __DIR__ . '/queries.php';
require_once __DIR__ . '/present.php';

const FOCUS_KINDS = ['department', 'agent', 'project', 'location', 'organization'];

/** The entity a focus kind is logged as — the same word its own screen's render options use. */
const FOCUS_ENTITY = [
    'department' => 'department', 'agent' => 'member', 'project' => 'project',
    'location' => 'location', 'organization' => 'organization',
];

function focus_graph(PDO $pdo, string $kind, int $id): ?array
{
    $built = match ($kind) {
        'department'   => focus_department($pdo, $id),
        'agent'        => focus_agent($pdo, $id),
        'location'     => focus_location($pdo, $id),
        default        => null,
    };
    if ($built === null) {
        return null;
    }
    [$centre, $rings] = $built;
    return focus_assemble($kind, $id, $centre, $rings);
}

/**
 * Centre + rings → the payload. A ring is [key, name, nodes, trueCount]; trueCount is what the
 * screen's list holds, which may be more than the nodes that fit (the per-ring and per-graph
 * caps), and a ring that was cut says so rather than implying it is complete.
 */
function focus_assemble(string $kind, int $id, array $centre, array $rings): array
{
    $nodes = [$centre];
    $edges = [];
    $room = FOCUS_GRAPH_CAP - 1;
    $groupCount = 0;

    foreach ($rings as [$key, $name, $members, $trueCount]) {
        // The centre is its own level-0 node, and a record sits on one ring only.
        $seen = [$centre['id'] => true];
        foreach ($nodes as $n) {
            $seen[$n['id']] = true;
        }
        $listed = count($members);
        $members = array_values(array_filter($members, static function (array $n) use (&$seen): bool {
            if (isset($seen[$n['id']])) {
                return false;
            }
            $seen[$n['id']] = true;
            return true;
        }));
        $trueCount = max(count($members), $trueCount - ($listed - count($members)));

        $room--;                                           // the group node itself
        if ($room < 0) {
            break;
        }
        $shown = array_slice($members, 0, max(0, min(FOCUS_GROUP_CAP, $room)));
        $room -= count($shown);

        $group = present_focus_group($key, $name, $trueCount, count($shown) < $trueCount);
        $nodes[] = $group;
        $groupCount++;
        $edges[] = ['source' => $centre['id'], 'target' => $group['id'], 'kind' => 'centre_of'];
        foreach ($shown as $n) {
            $nodes[] = $n;
            $edges[] = ['source' => $group['id'], 'target' => $n['id'], 'kind' => 'has_member'];
        }
    }

    return [
        'generated_at' => gmdate('c'),
        'focus'        => ['kind' => $kind, 'id' => $id],
        'centre'       => [
            'id' => $centre['id'], 'name' => $centre['name'], 'title' => $centre['title'], 'href' => $centre['href'],
        ],
        'summary'      => ['groups' => $groupCount, 'nodes' => count($nodes)],
        'nodes'        => $nodes,
        'edges'        => $edges,
    ];
}

/**
 * Member nodes for a list of rows that carry a member id. Name, kind, job title and picture
 * come from orgchart_member_identities() — the read the home Agent View already makes — so a
 * face here is the face there. A member the directory does not return is not drawn.
 * $titleOf, when given, supplies the line under the name from the screen's own row (a project
 * role, "Primary", an agent's role key); otherwise it is the job title.
 */
function focus_member_nodes(PDO $pdo, array $rows, string $idKey, ?callable $titleOf = null): array
{
    $ids = array_values(array_unique(array_map(static fn (array $r): int => (int) $r[$idKey], $rows)));
    $identities = orgchart_member_identities($pdo, $ids);
    $nodes = [];
    foreach ($rows as $r) {
        $mid = (int) $r[$idKey];
        $who = $identities[$mid] ?? null;
        if ($who === null) {
            continue;
        }
        $title = $titleOf !== null ? $titleOf($r) : null;
        $nodes[] = present_focus_node('member', $mid, (string) $who['display_name'],
            $title ?? $who['job_title'],
            ['member_kind' => $who['member_kind'], 'avatar_url' => $who['avatar_url']]);
    }
    return $nodes;
}

// --------------------------------------------------------------------------
// department:<id> — html/team/departments/view.php (gate: admin)
// --------------------------------------------------------------------------
function focus_department(PDO $pdo, int $id): ?array
{
    require_once dirname(__DIR__) . '/team/queries.php';
    if (!is_business_admin() || ($department = find_department($pdo, $id)) === null) {
        return null;
    }
    $members = department_members($pdo, $id);
    $people = array_values(array_filter($members, static fn (array $m): bool => $m['member_kind'] !== 'agent'));
    $agents = array_values(array_filter($members, static fn (array $m): bool => $m['member_kind'] === 'agent'));
    $role = static fn (array $m): ?string => !empty($m['is_admin']) ? 'Department admin' : null;

    $children = array_values(array_filter(find_departments($pdo),
        static fn (array $d): bool => (int) ($d['parent_id'] ?? 0) === $id));

    $lead = ($department['manager_name'] ?? '') !== '' ? 'Led by ' . $department['manager_name'] : null;
    return [
        present_focus_centre('department', $id, (string) $department['name'], $lead),
        [
            ['people', 'People', focus_member_nodes($pdo, $people, 'member_id', $role), count($people)],
            ['agents', 'Agents', focus_member_nodes($pdo, $agents, 'member_id', $role), count($agents)],
            ['sub-departments', 'Sub-departments', array_map(static fn (array $d): array => present_focus_node(
                'department', (int) $d['department_id'], (string) $d['name'],
                ($d['manager_name'] ?? '') !== '' ? 'Led by ' . $d['manager_name'] : null), $children), count($children)],
        ],
    ];
}

// --------------------------------------------------------------------------
// agent:<member id> — html/agents/view.php (gate: insider)
// --------------------------------------------------------------------------
function focus_agent(PDO $pdo, int $id): ?array
{
    require_once dirname(__DIR__) . '/agents/render.php';
    agents_require_files();
    if (is_external_member() || ($agent = find_agent($pdo, $id)) === null) {
        return null;
    }
    $kind = (string) ($agent['agent_kind'] ?? 'subagent');
    $rings = [];

    // A voice agent has no roster (db/091): it employs nobody and is employed by nobody.
    if ($kind === 'orchestrator') {
        $roster = find_agent_roster($pdo, $id);
        $rings[] = ['roster', 'Roster', focus_member_nodes($pdo, $roster, 'subagent_member_id',
            static fn (array $r): ?string => ($r['subagent_role_key'] ?? '') !== '' ? (string) $r['subagent_role_key'] : null),
            count($roster)];
    } elseif ($kind !== 'voice') {
        $orchestrators = find_agent_orchestrators($pdo, $id);
        $rings[] = ['orchestrators', 'Orchestrators',
            focus_member_nodes($pdo, $orchestrators, 'orchestrator_member_id'), count($orchestrators)];
    }

    $grants = find_agent_tool_grants($pdo, $id);
    $rings[] = ['tools', 'Tools', array_map(static fn (array $g): array => present_focus_node(
        'tool', (int) $g['agent_tool_grant_id'], (string) $g['tool_name'],
        trim(($g['application_name'] ?? '') . ' — ' . ($g['endpoint_name'] ?? ''), ' —')), $grants), count($grants)];

    $duties = find_agent_duties($pdo, $id);
    $rings[] = ['duties', 'Duties', array_map(static fn (array $d): array => present_focus_node(
        'duty', (int) $d['duty_id'], (string) $d['name'],
        !empty($d['active']) ? (string) $d['schedule_cron'] : 'Paused'), $duties), count($duties)];

    $identity = orgchart_member_identities($pdo, [$id])[$id] ?? null;
    return [
        present_focus_centre('member', $id, (string) $agent['display_name'],
            ($agent['job_title'] ?? '') !== '' ? (string) $agent['job_title'] : null,
            ['member_kind' => 'agent', 'avatar_url' => $identity['avatar_url'] ?? null]),
        $rings,
    ];
}

// --------------------------------------------------------------------------
// location:<id> — html/locations/view.php (gate: insider)
// --------------------------------------------------------------------------
function focus_location(PDO $pdo, int $id): ?array
{
    require_once dirname(__DIR__) . '/estate/render.php';
    estate_require_files();
    if (is_external_member() || ($location = find_location($pdo, $id)) === null) {
        return null;
    }
    $residents = find_location_residents($pdo, $id);
    $departments = find_location_departments($pdo, $id);
    $applications = find_location_applications($pdo, $id);
    // What is inside it: the estate list's own read, filtered to this parent. One page of it —
    // total_count carries the true number, so a crowded building says it was cut.
    $inside = find_locations($pdo, ['parent_location_id' => $id], 'kind', 1);
    $insideTotal = (int) ($inside[0]['total_count'] ?? 0);

    return [
        present_focus_centre('location', $id, (string) $location['name'],
            ucfirst((string) $location['kind']) . ' · ' . ucfirst((string) $location['status'])),
        [
            ['residents', 'Residents', focus_member_nodes($pdo, $residents, 'member_id',
                static fn (array $r): ?string => !empty($r['is_office_manager']) ? 'Office manager' : null), count($residents)],
            ['departments', 'Departments', array_map(static fn (array $d): array => present_focus_node(
                'department', (int) $d['department_id'], (string) $d['name'],
                ($d['manager_name'] ?? '') !== '' ? 'Led by ' . $d['manager_name'] : null), $departments), count($departments)],
            ['applications', 'Applications', array_map(static fn (array $a): array => present_focus_node(
                'application', (int) $a['application_id'], (string) $a['name'],
                ucwords(str_replace('_', ' ', (string) $a['category']))), $applications), count($applications)],
            ['inside', 'Inside', array_map(static fn (array $l): array => present_focus_node(
                'location', (int) $l['location_id'], (string) $l['name'], ucfirst((string) $l['kind'])), $inside), $insideTotal],
        ],
    ];
}

