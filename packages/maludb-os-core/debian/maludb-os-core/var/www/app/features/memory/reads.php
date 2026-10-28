<?php
declare(strict_types=1);

/**
 * What the signed-in member may READ in shared memory — the Memory MCP server's rules
 * (mcp/memory_server.py), restated for the two screen reads. Scope comes from the session,
 * never from the request: there is no namespace or principal parameter to get wrong.
 */

/**
 * The caller's read scope set, optionally narrowed; never wider.
 * @return list<array{namespace: string, label: string}>
 */
function memory_read_scopes(PDO $pdo, ?string $scope): array
{
    $own = [['namespace' => memory_principal_ref((int) current_member_id(), member_kind()), 'label' => 'you']];
    $departments = [];
    foreach (memory_my_departments($pdo) as $d) {
        $departments[] = ['namespace' => 'dept:' . $d['id'], 'label' => $d['name']];
    }
    $org = [['namespace' => 'org', 'label' => 'the organisation']];
    return match ($scope) {
        'self' => $own,
        'department' => $departments,
        'org' => $org,
        default => array_merge($own, $departments, $org),
    };
}

/** @return list<array{id: int, name: string}> */
function memory_my_departments(PDO $pdo): array
{
    $ids = array_map('intval', my_department_ids($pdo));
    if ($ids === []) {
        return [];
    }
    $in = implode(',', array_fill(0, count($ids), '?'));
    $st = $pdo->prepare("SELECT department_id AS id, name FROM mcp_departments WHERE department_id IN ($in) ORDER BY name");
    $st->execute($ids);
    return array_map(static fn (array $r): array => ['id' => (int) $r['id'], 'name' => (string) $r['name']], $st->fetchAll());
}

/**
 * May the caller read $memberId's core memory? Oneself; mod:hr; an agent one may see in full.
 * @return array{0: bool, 1: ?array}  [allowed, the member as the directory shows it]
 */
function memory_may_read_core(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare('SELECT member_id, display_name, member_kind, app_can_see_agent(member_id) AS sees_agent
                           FROM mcp_team_directory WHERE member_id = :id');
    $st->execute(['id' => $memberId]);
    $member = $st->fetch();
    if ($member === false) {
        return [false, null];
    }
    $allowed = $memberId === (int) current_member_id()
        || is_super_admin() || has_module($pdo, 'hr')
        || ($member['member_kind'] === 'agent' && (bool) $member['sees_agent']);
    return [$allowed, $member];
}

/** The agents whose core memory the caller may open — for the links on /memory. */
function memory_openable_agents(PDO $pdo): array
{
    $all = is_super_admin() || has_module($pdo, 'hr');
    $st = $pdo->prepare("SELECT agent_member_id, display_name, job_title
                           FROM mcp_agents
                          WHERE status IN ('active', 'suspended', 'candidate')
                            AND (:all OR app_can_see_agent(agent_member_id))
                          ORDER BY display_name LIMIT 100");
    $st->bindValue('all', $all, PDO::PARAM_BOOL);
    $st->execute();
    return $st->fetchAll();
}

/**
 * Recall over the caller's scopes. @return array{0: ?array, 1: ?string} [MaluDB's answer, a
 * sentence when memory could not be asked]
 */
function memory_recall(array $scopes, string $query, ?string $subject, int $limit = 12): array
{
    try {
        $r = maludb_request('POST', '/v1/memory/recall', array_filter([
            'query' => $query, 'namespaces' => array_column($scopes, 'namespace'),
            'subject' => $subject, 'limit' => $limit,
        ], static fn ($v) => $v !== null));
    } catch (RuntimeException $ex) {
        return [null, $ex->getMessage()];
    }
    if ($r['status'] < 200 || $r['status'] >= 300) {
        return [null, maludb_error($r)];
    }
    return [$r['body'], null];
}

/** @return array{0: ?array, 1: ?string} */
function memory_profile(string $ref): array
{
    try {
        $r = maludb_request('GET', '/v1/principals/' . rawurlencode($ref) . '/profile');
    } catch (RuntimeException $ex) {
        return [null, $ex->getMessage()];
    }
    if ($r['status'] < 200 || $r['status'] >= 300) {
        return [null, maludb_error($r)];
    }
    return [$r['body'], null];
}
