<?php
declare(strict_types=1);

/**
 * The AI Agent View org graph (build spec: docs/build-specs/public-api-org-graph.md).
 *
 * Every read goes through mcp_departments, mcp_department_members, mcp_agents and
 * mcp_team_directory — never a base table — and this file adds NO scoping of its own.
 *
 * It briefly did. The build spec assumed those views scope per viewer; they do not, being
 * gated on app_is_insider() alone, so the first build added a rule restricting the graph to
 * the caller's own and administered departments. Owner's decision 2026-09-18: **the whole
 * organisation is visible to anyone who works here** — only the centre node differs by
 * viewer. That is what the views were deliberately built for, and what question H1 ("who
 * works in department X, and who manages it?", audience: all) asks for. The departments
 * SCREEN stays admin-gated; an org chart is a reading surface, not an admin one.
 *
 * So the rule was removed rather than kept. The API now has no visibility logic at all,
 * which is the point: a second implementation is how a screen and an agent end up
 * disagreeing, and this project has found that seven times already.
 */

/**
 * Identity + avatar for a set of member ids, in one query. avatar_url resolves exactly as
 * the spec requires — an agent's uploaded photo (mcp_agents.profile_pic_url) else
 * default_avatar_url(member_id) — read here in SQL, never rebuilt in PHP. A member whose
 * member_kind is 'agent' but who has no agent_profiles row (a data gap, not ours to fix)
 * simply gets agent_status = NULL, which orgchart_member_node() reads as "no agent detail
 * to show" rather than inventing one.
 */
function orgchart_member_identities(PDO $pdo, array $memberIds): array
{
    if ($memberIds === []) {
        return [];
    }
    $st = $pdo->prepare(<<<'SQL'
        SELECT
            td.member_id,
            td.display_name,
            td.job_title,
            td.member_kind,
            td.status                                              AS member_status,
            a.status                                                AS agent_status,
            a.agent_kind,
            a.role_key,
            a.manager_member_id                                     AS agent_manager_member_id,
            a.is_office_manager,
            COALESCE(a.profile_pic_url, default_avatar_url(td.member_id)) AS avatar_url
          FROM mcp_team_directory td
          LEFT JOIN mcp_agents a ON a.agent_member_id = td.member_id
         WHERE td.member_id = ANY (:ids::bigint[])
    SQL);
    $st->bindValue('ids', pg_array_literal($memberIds));
    $st->execute();
    $byId = [];
    foreach ($st->fetchAll() as $row) {
        $byId[(int) $row['member_id']] = $row;
    }
    return $byId;
}

/** One member node (id-prefixed, raw id also present — spec "Fixed rules for the payload"). */
function orgchart_member_node(int $memberId, array $identity, int $level, bool $isCentre): array
{
    $node = [
        'id'          => 'member:' . $memberId,
        'type'        => 'member',
        'level'       => $level,
        'member_id'   => $memberId,
        'name'        => $identity['display_name'],
        'title'       => $identity['job_title'],
        'member_kind' => $identity['member_kind'],
        'avatar_url'  => $identity['avatar_url'],
    ];
    if ($isCentre) {
        $node['is_centre'] = true;
    }
    // 'agent' only when mcp_agents actually has a row for this member — never reconstructed,
    // never a budget figure (mcp_agents already masks that behind app_can_see_agent()).
    if ($identity['member_kind'] === 'agent' && $identity['agent_status'] !== null) {
        $node['agent'] = [
            'status'             => $identity['agent_status'],
            'agent_kind'         => $identity['agent_kind'],   // orchestrator | subagent | voice — passed through, never enumerated as a pair
            'role_key'           => $identity['role_key'],
            'manager_member_id'  => $identity['agent_manager_member_id'] !== null
                ? (int) $identity['agent_manager_member_id'] : null,
            'is_office_manager'  => $identity['is_office_manager'] !== null
                ? (bool) $identity['is_office_manager'] : null,
        ];
    }
    return $node;
}

/**
 * The whole AI Agent View payload for one caller. Centre is always the caller
 * ($centreMemberId); v1 takes no root parameter (spec).
 */
function org_graph(PDO $pdo, int $centreMemberId, bool $includeRetired): array
{
    // No department filter: the view decides who may read it, and it is insider-open by design.
    $st = $pdo->prepare(<<<'SQL'
        SELECT department_id, name, parent_id, manager_member_id, manager_name, archived_at
          FROM mcp_departments
         WHERE (:includeRetired OR archived_at IS NULL)
         ORDER BY department_id
    SQL);
    $st->bindValue('includeRetired', $includeRetired, PDO::PARAM_BOOL);
    $st->execute();
    $departments = $st->fetchAll();
    $deptIds = array_map(static fn (array $d): int => (int) $d['department_id'], $departments);

    $deptMembers = [];
    if ($deptIds !== []) {
        $st = $pdo->prepare(<<<'SQL'
            SELECT department_id, member_id, member_kind
              FROM mcp_department_members
             WHERE department_id = ANY (:ids::bigint[])
             ORDER BY department_id, member_id
        SQL);
        $st->bindValue('ids', pg_array_literal($deptIds));
        $st->execute();
        $deptMembers = $st->fetchAll();
    }

    // Distinct level-2 candidates: every department member who is not the centre (the
    // centre is its own level-0 node, never duplicated at level 2).
    $level2Ids = [];
    foreach ($deptMembers as $row) {
        $mid = (int) $row['member_id'];
        if ($mid !== $centreMemberId) {
            $level2Ids[$mid] = true;
        }
    }
    $level2Ids = array_keys($level2Ids);

    $allIds = array_values(array_unique(array_merge([$centreMemberId], $level2Ids)));
    $identities = orgchart_member_identities($pdo, $allIds);
    $centreIdentity = $identities[$centreMemberId] ?? null;

    // Retirement (spec: include_retired, default false) applies to agents only — an
    // offboarded agent is "retired"; everything else (mcp_team_directory already excludes
    // offboarded humans on its own) passes through unfiltered. Mirrors the existing
    // find_agents() convention (`status <> 'offboarded'` by default).
    $visibleLevel2 = [];
    foreach ($level2Ids as $mid) {
        $identity = $identities[$mid] ?? null;
        if ($identity === null) {
            continue;
        }
        if (!$includeRetired && $identity['member_kind'] === 'agent' && $identity['agent_status'] === 'offboarded') {
            continue;
        }
        $visibleLevel2[$mid] = $identity;
    }

    // One pass to tally each department's visible human/agent counts, shared by the
    // department nodes and the teams array so the two can never disagree (spec: "two calls
    // would let the counts disagree with the graph" — same principle, one computation).
    $tally = [];
    foreach ($deptIds as $deptId) {
        $tally[$deptId] = ['human' => 0, 'agent' => 0];
    }
    foreach ($deptMembers as $row) {
        $deptId = (int) $row['department_id'];
        $mid = (int) $row['member_id'];
        if ($mid === $centreMemberId || !isset($visibleLevel2[$mid])) {
            continue;
        }
        $tally[$deptId][$row['member_kind'] === 'agent' ? 'agent' : 'human']++;
    }

    $nodes = [];
    $edges = [];

    foreach ($departments as $dept) {
        $deptId = (int) $dept['department_id'];
        $nodes[] = [
            'id'                    => 'department:' . $deptId,
            'type'                  => 'department',
            'level'                 => 1,
            'department_id'         => $deptId,
            'name'                  => $dept['name'],
            'parent_department_id'  => $dept['parent_id'] !== null ? (int) $dept['parent_id'] : null,
            'manager'               => $dept['manager_member_id'] !== null ? [
                'id'   => 'member:' . (int) $dept['manager_member_id'],
                'name' => $dept['manager_name'],
            ] : null,
            'member_count'          => $tally[$deptId]['human'],
            'agent_count'           => $tally[$deptId]['agent'],
        ];
        // The centre joins to EVERY department, not only the ones it belongs to: the graph is
        // the organisation seen from where you sit, and a centre with no edges is a floating
        // dot. So the edge is named for what it is — the spoke from the centre — rather than
        // 'member_of', which would assert a membership the centre may not have. (Verified: the
        // super-admin belongs to no department and still has six spokes.)
        $edges[] = [
            'source' => 'member:' . $centreMemberId,
            'target' => 'department:' . $deptId,
            'kind'   => 'centre_of',
        ];
    }

    foreach ($deptMembers as $row) {
        $mid = (int) $row['member_id'];
        if ($mid === $centreMemberId || !isset($visibleLevel2[$mid])) {
            continue;
        }
        $edges[] = [
            'source' => 'department:' . (int) $row['department_id'],
            'target' => 'member:' . $mid,
            'kind'   => 'has_member',
        ];
    }

    foreach ($visibleLevel2 as $mid => $identity) {
        $nodes[] = orgchart_member_node($mid, $identity, 2, false);
    }

    $centreNode = null;
    if ($centreIdentity !== null) {
        $centreNode = orgchart_member_node($centreMemberId, $centreIdentity, 0, true);
        array_unshift($nodes, $centreNode);
    }

    $peopleCount = 0;
    $agentsCount = 0;
    if ($centreIdentity !== null) {
        if ($centreIdentity['member_kind'] === 'agent') {
            $agentsCount++;
        } else {
            $peopleCount++;
        }
    }
    foreach ($visibleLevel2 as $identity) {
        if ($identity['member_kind'] === 'agent') {
            $agentsCount++;
        } else {
            $peopleCount++;
        }
    }

    $teams = array_map(static function (array $dept) use ($tally): array {
        $deptId = (int) $dept['department_id'];
        return [
            'department_id' => $deptId,
            'name'          => $dept['name'],
            'member_count'  => $tally[$deptId]['human'],
            'agent_count'   => $tally[$deptId]['agent'],
        ];
    }, $departments);

    return [
        'generated_at' => gmdate('c'),
        'centre'       => $centreNode !== null ? [
            'id'          => $centreNode['id'],
            'member_id'   => $centreNode['member_id'],
            'name'        => $centreNode['name'],
            'title'       => $centreNode['title'],
            'member_kind' => $centreNode['member_kind'],
            'avatar_url'  => $centreNode['avatar_url'],
        ] : null,
        'summary'      => [
            'people' => $peopleCount,
            'agents' => $agentsCount,
            'teams'  => count($departments),
            'levels' => 3,   // centre / departments / members — fixed by design, not computed from edges
        ],
        'teams'        => $teams,
        'nodes'        => $nodes,
        'edges'        => $edges,
    ];
}

/**
 * One node's detail: the member, their departments, their manager, and — for an agent — its
 * model, status, role, agent_kind and (only for an orchestrator) its roster. Returns null
 * when the member does not exist or the caller cannot see them (mcp_team_directory already
 * decides that): the caller maps null to 404, never 403.
 */
function member_node_detail(PDO $pdo, int $memberId): ?array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT
            td.member_id, td.display_name, td.job_title, td.member_kind,
            a.status                AS agent_status,
            a.agent_kind,
            a.role_key,
            a.model_key,
            a.harness,
            a.manager_member_id     AS agent_manager_member_id,
            a.manager_name          AS agent_manager_name,
            a.is_office_manager,
            a.hired_at, a.suspended_at, a.offboarded_at,
            COALESCE(a.profile_pic_url, default_avatar_url(td.member_id)) AS avatar_url
          FROM mcp_team_directory td
          LEFT JOIN mcp_agents a ON a.agent_member_id = td.member_id
         WHERE td.member_id = :id
    SQL);
    $st->execute(['id' => $memberId]);
    $identity = $st->fetch();
    if ($identity === false) {
        return null;
    }

    $deptSt = $pdo->prepare(<<<'SQL'
        SELECT department_id, department_name, is_primary
          FROM mcp_department_members
         WHERE member_id = :id
         ORDER BY is_primary DESC, department_name
    SQL);
    $deptSt->execute(['id' => $memberId]);
    $departments = $deptSt->fetchAll();

    // Manager: an agent's own manager, read straight off mcp_agents. It is NOT always human —
    // an active orchestrator agent may manage a subagent (2026-09-18, owner), so this passes
    // through whatever the view resolved and never assumes a kind. A human's manager is their
    // primary department's manager, the org-chart sense the estate and HR slices already use,
    // since a human member has no separate reports-to column.
    $manager = null;
    if ($identity['agent_manager_member_id'] !== null) {
        $manager = [
            'id'   => 'member:' . (int) $identity['agent_manager_member_id'],
            'name' => $identity['agent_manager_name'],
        ];
    } else {
        $primary = null;
        foreach ($departments as $d) {
            if ($d['is_primary']) {
                $primary = $d;
                break;
            }
        }
        $primary ??= ($departments[0] ?? null);
        if ($primary !== null) {
            $mSt = $pdo->prepare('SELECT manager_member_id, manager_name FROM mcp_departments WHERE department_id = :id');
            $mSt->execute(['id' => $primary['department_id']]);
            $deptRow = $mSt->fetch();
            if ($deptRow !== false && $deptRow['manager_member_id'] !== null
                && (int) $deptRow['manager_member_id'] !== $memberId) {
                $manager = [
                    'id'   => 'member:' . (int) $deptRow['manager_member_id'],
                    'name' => $deptRow['manager_name'],
                ];
            }
        }
    }

    $detail = [
        'id'          => 'member:' . $memberId,
        'member_id'   => $memberId,
        'name'        => $identity['display_name'],
        'title'       => $identity['job_title'],
        'member_kind' => $identity['member_kind'],
        'avatar_url'  => $identity['avatar_url'],
        'departments' => array_map(static fn (array $d): array => [
            'department_id' => (int) $d['department_id'],
            'name'          => $d['department_name'],
            'is_primary'    => (bool) $d['is_primary'],
        ], $departments),
        'manager'     => $manager,
    ];

    if ($identity['agent_status'] !== null) {
        $agent = [
            'status'            => $identity['agent_status'],
            'agent_kind'        => $identity['agent_kind'],   // orchestrator | subagent | voice
            'role_key'          => $identity['role_key'],
            'model_key'         => $identity['model_key'],
            'harness'           => $identity['harness'],
            'is_office_manager' => $identity['is_office_manager'] !== null
                ? (bool) $identity['is_office_manager'] : null,
            'hired_at'          => $identity['hired_at'],
            'suspended_at'      => $identity['suspended_at'],
            'offboarded_at'     => $identity['offboarded_at'],
        ];
        // The orchestrator→subagent roster — never for a voice agent, which employs nobody
        // and is employed by nobody (outside the delegation tree entirely).
        if ($identity['agent_kind'] === 'orchestrator') {
            $rosterSt = $pdo->prepare(<<<'SQL'
                SELECT subagent_member_id, subagent_name, subagent_status, subagent_role_key
                  FROM mcp_agent_subagents
                 WHERE orchestrator_member_id = :id AND removed_at IS NULL
                 ORDER BY subagent_name
            SQL);
            $rosterSt->execute(['id' => $memberId]);
            $agent['roster'] = array_map(static fn (array $r): array => [
                'id'       => 'member:' . (int) $r['subagent_member_id'],
                'name'     => $r['subagent_name'],
                'status'   => $r['subagent_status'],
                'role_key' => $r['subagent_role_key'],
            ], $rosterSt->fetchAll());
        }
        $detail['agent'] = $agent;
    }

    return $detail;
}
