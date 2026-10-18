<?php
declare(strict_types=1);

/**
 * Team & access query functions (shell conversion, build plan 1.8).
 *
 * Three roles and only three: super_admin, dept_admin, user — with "external" as a flag.
 * Reads go through the mcp_* views, so an administrator sees exactly the people and grants
 * the rules allow (a dept-admin sees their departments; a super-admin sees everyone).
 * Writes go to the base tables after the endpoint's gate.
 */

const TEAM_PAGE_SIZE = 50;
const TEAM_SORT_ALLOWED = ['display_name', 'business_role', 'joined_at'];

/** The 23 grantable modules (module_grants CHECK) with their labels, for the access editor. */
function grantable_modules(): array
{
    // The kernel's own applications (db/133 shrank module_grants to this set, 2026-09-22). An
    // application from us is admitted by an application access grant, never a module grant.
    return [
        'hr' => 'Agent HR', 'ledger' => 'AI ops', 'evals' => 'Evals', 'approvals' => 'Approvals',
        'locations' => 'Work Locations', 'applications' => 'Applications',
    ];
}

function team_members(PDO $pdo, string $q = '', ?int $departmentId = null, string $kind = 'both',
                      string $role = '', string $sort = 'display_name', int $page = 1): array
{
    $sort = in_array($sort, TEAM_SORT_ALLOWED, true) ? $sort : 'display_name';
    $page = max(1, $page);
    $offset = ($page - 1) * TEAM_PAGE_SIZE;

    $where = ['1 = 1'];
    $params = [];
    if (trim($q) !== '') {
        $where[] = '(t.display_name ILIKE :q OR t.email ILIKE :q)';
        $params['q'] = '%' . trim($q) . '%';
    }
    if ($kind === 'human' || $kind === 'agent') {
        $where[] = 't.member_kind = :kind';
        $params['kind'] = $kind;
    }
    if ($role !== '' && in_array($role, ['super_admin', 'dept_admin', 'user'], true)) {
        $where[] = 't.business_role = :role';
        $params['role'] = $role;
    }
    if ($departmentId !== null) {
        $where[] = 'EXISTS (SELECT 1 FROM mcp_department_members dm
                             WHERE dm.member_id = t.member_id AND dm.department_id = :dept)';
        $params['dept'] = $departmentId;
    }
    $whereSql = implode(' AND ', $where);

    $sql = "
        SELECT t.*, count(*) OVER() AS total_count
          FROM mcp_team_directory t
         WHERE {$whereSql}
         ORDER BY t.{$sort} ASC
         LIMIT :lim OFFSET :off
    ";
    $st = $pdo->prepare($sql);
    foreach ($params as $k => $v) {
        $st->bindValue($k, $v);
    }
    $st->bindValue('lim', TEAM_PAGE_SIZE, PDO::PARAM_INT);
    $st->bindValue('off', $offset, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}

function find_team_member(PDO $pdo, int $memberId): ?array
{
    $st = $pdo->prepare('SELECT * FROM mcp_team_directory WHERE member_id = :id');
    $st->execute(['id' => $memberId]);
    return ($r = $st->fetch()) === false ? null : $r;
}

function member_departments(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT department_id, department_name, is_admin, is_primary, joined_at
          FROM mcp_department_members
         WHERE member_id = :id AND left_at IS NULL
         ORDER BY department_name
    SQL);
    $st->execute(['id' => $memberId]);
    return $st->fetchAll();
}

function member_module_grants(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare('SELECT module, access, created_at AS granted_at FROM mcp_module_grants WHERE member_id = :id ORDER BY module');
    $st->execute(['id' => $memberId]);
    $out = [];
    foreach ($st->fetchAll() as $row) {
        $out[$row['module']] = $row;
    }
    return $out;
}

// ---- writes ---------------------------------------------------------------

function set_member_role(PDO $pdo, int $memberId, string $role): array
{
    $st = $pdo->prepare('UPDATE members SET business_role = :r WHERE id = :id RETURNING id, display_name, business_role');
    $st->execute(['r' => $role, 'id' => $memberId]);
    return $st->fetch() ?: [];
}

function set_member_external(PDO $pdo, int $memberId, bool $isExternal): array
{
    $st = $pdo->prepare('UPDATE members SET is_external = :x WHERE id = :id RETURNING id, display_name, is_external');
    $st->execute(['x' => $isExternal ? 't' : 'f', 'id' => $memberId]);
    return $st->fetch() ?: [];
}

function set_module_grant(PDO $pdo, int $memberId, string $module, string $access, int $grantedBy): array
{
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO module_grants (member_id, module, access, granted_by)
        VALUES (:m, :mod, :acc, :by)
        ON CONFLICT (member_id, module) DO UPDATE SET access = EXCLUDED.access, granted_by = EXCLUDED.granted_by
        RETURNING member_id, module, access
    SQL);
    $st->execute(['m' => $memberId, 'mod' => $module, 'acc' => $access, 'by' => $grantedBy]);
    return $st->fetch() ?: [];
}

function revoke_module_grant(PDO $pdo, int $memberId, string $module): bool
{
    $st = $pdo->prepare('DELETE FROM module_grants WHERE member_id = :m AND module = :mod');
    $st->execute(['m' => $memberId, 'mod' => $module]);
    return $st->rowCount() > 0;
}

// ---- departments ----------------------------------------------------------

/**
 * The org chart reads from the top: the Front Office first (every other department reports
 * to it, db/074), then the rest of the standing departments, then everyone else by name.
 */
function find_departments(PDO $pdo, bool $includeArchived = false): array
{
    $sql = 'SELECT * FROM mcp_departments' . ($includeArchived ? '' : ' WHERE archived_at IS NULL')
         . " ORDER BY (system_key = 'front_office') DESC NULLS LAST, is_system DESC, name";
    return $pdo->query($sql)->fetchAll();
}

/** The Front Office row out of a department list already fetched, or null if it is not there. */
function front_office_department(array $departments): ?array
{
    foreach ($departments as $d) {
        if (($d['system_key'] ?? null) === 'front_office') {
            return $d;
        }
    }
    return null;
}

function find_department(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT * FROM mcp_departments WHERE department_id = :id');
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

function department_members(PDO $pdo, int $departmentId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT member_id, display_name AS member_name, member_kind, is_admin, is_primary, joined_at
          FROM mcp_department_members
         WHERE department_id = :id AND left_at IS NULL
         ORDER BY is_admin DESC, display_name
    SQL);
    $st->execute(['id' => $departmentId]);
    return $st->fetchAll();
}

/**
 * Every live application grant that reaches one member (the app_member_grants() rule): their own,
 * which the member page edits, and those that come through a department they are in or a site
 * they reside at, which it only names — they are changed on the department or the application.
 */
function member_application_grants(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT ac.id AS application_access_id, a.id AS application_id, a.name AS application_name, a.scope_kind,
               CASE WHEN ac.member_id IS NOT NULL THEN 'member'
                    WHEN ac.department_id IS NOT NULL THEN 'department' ELSE 'residents' END AS route,
               COALESCE(d.name::text, rl.name) AS through_name, COALESCE(ac.department_id, ac.resident_location_id) AS through_id,
               ac.scope_id, COALESCE(sl.name, sd.name::text) AS scope_name,
               ac.role_key, r.name AS role_name, ac.capability, ac.expires_at,
               -- db/145: every role the grant gives, [{key, name, withdrawn}]
               COALESCE((SELECT jsonb_agg(jsonb_build_object('key', x.role_key, 'name', xr.name, 'withdrawn', xr.withdrawn_at IS NOT NULL)
                                          ORDER BY xr.sort_order, xr.id)
                           FROM application_access_roles x
                           JOIN application_roles xr ON xr.application_id = x.application_id AND xr.role_key = x.role_key
                          WHERE x.application_access_id = ac.id), '[]'::jsonb) AS roles
          FROM application_access ac
          JOIN applications a ON a.id = ac.application_id AND a.status <> 'retired'
          LEFT JOIN departments d ON d.id = ac.department_id
          LEFT JOIN locations rl ON rl.id = ac.resident_location_id
          LEFT JOIN application_scopes s ON s.id = ac.scope_id
          LEFT JOIN locations sl ON sl.id = s.location_id
          LEFT JOIN departments sd ON sd.id = s.department_id
          LEFT JOIN application_roles r ON r.application_id = ac.application_id AND r.role_key = ac.role_key
         WHERE ac.revoked_at IS NULL
           AND (ac.expires_at IS NULL OR ac.expires_at > now())
           AND (ac.scope_id IS NULL OR s.removed_at IS NULL)
           AND (ac.member_id = :m
                OR ac.department_id IN (SELECT department_id FROM department_members WHERE member_id = :m AND left_at IS NULL)
                OR ac.resident_location_id IN (SELECT location_id FROM location_residents WHERE member_id = :m AND removed_at IS NULL))
         ORDER BY a.name, ac.member_id IS NULL, scope_name
    SQL);
    $st->execute(['m' => $memberId]);
    return $st->fetchAll();
}

/**
 * The applications a person can be granted, each with the roles it declares and the sites or
 * departments it serves: every live application except the kernel's own rows (built-in modules
 * and the platform), which admit through the business role and module grants instead.
 */
function grantable_applications(PDO $pdo): array
{
    $apps = $pdo->query("SELECT id, name, scope_kind FROM applications
                          WHERE status <> 'retired' AND NOT is_builtin AND app_key <> 'platform'
                          ORDER BY name")->fetchAll();
    if ($apps === []) {
        return [];
    }
    $roles = [];
    // Roles still offered (db/145: a withdrawn role is never granted anew), with what each gives.
    foreach ($pdo->query('SELECT application_id, role_key, name, capability, description, rights FROM application_roles
                           WHERE withdrawn_at IS NULL ORDER BY application_id, sort_order, id')->fetchAll() as $r) {
        $roles[(int) $r['application_id']][] = $r;
    }
    $scopes = [];
    foreach ($pdo->query('SELECT s.application_id, s.id, COALESCE(l.name, d.name::text) AS name
                            FROM application_scopes s
                            LEFT JOIN locations l ON l.id = s.location_id
                            LEFT JOIN departments d ON d.id = s.department_id
                           WHERE s.removed_at IS NULL ORDER BY 3')->fetchAll() as $s) {
        $scopes[(int) $s['application_id']][] = $s;
    }
    foreach ($apps as &$a) {
        $a['roles'] = $roles[(int) $a['id']] ?? [];
        $a['scopes'] = $scopes[(int) $a['id']] ?? [];
    }
    return $apps;
}

/**
 * The applications a department is tied to, one row per tie: it owns the application, the
 * application serves it (a live department scope, db/141), or the department holds a live grant
 * (everyone in it can use the application, with that role or capability). Retired applications
 * are left out.
 */
function department_applications(PDO $pdo, int $departmentId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT a.id AS application_id, a.name, a.status, 'owns' AS tie, NULL::text AS role_key,
               NULL::text AS capability, NULL::text AS scope_name
          FROM applications a
         WHERE a.owner_department_id = :id AND a.status <> 'retired'
        UNION ALL
        SELECT a.id, a.name, a.status, 'serves', NULL, NULL, NULL
          FROM application_scopes s JOIN applications a ON a.id = s.application_id
         WHERE s.department_id = :id AND s.removed_at IS NULL AND a.status <> 'retired'
        UNION ALL
        SELECT a.id, a.name, a.status, 'granted', ac.role_key, ac.capability, COALESCE(l.name, d.name::text)
          FROM application_access ac
          JOIN applications a ON a.id = ac.application_id
          LEFT JOIN application_scopes s ON s.id = ac.scope_id
          LEFT JOIN locations l ON l.id = s.location_id
          LEFT JOIN departments d ON d.id = s.department_id
         WHERE ac.department_id = :id AND ac.revoked_at IS NULL
           AND (ac.expires_at IS NULL OR ac.expires_at > now())
           AND (ac.scope_id IS NULL OR s.removed_at IS NULL)
           AND a.status <> 'retired'
         ORDER BY 2, 4
    SQL);
    $st->execute(['id' => $departmentId]);
    return $st->fetchAll();
}

/**
 * What each live member of a department can use, by explicit grant — their own, a department's
 * they are in, or their site's (app_member_grants(), the rule sign-on uses). A super-admin's
 * implicit reach to everything is not listed. Keyed by member id, one row per application with
 * the strongest capability held.
 */
function department_member_applications(PDO $pdo, int $departmentId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT dm.member_id, a.id AS application_id, a.name,
               (array_agg(g.capability ORDER BY app_capability_rank(g.capability) DESC))[1] AS capability
          FROM department_members dm
          JOIN applications a ON a.status <> 'retired'
          CROSS JOIN LATERAL app_member_grants(a.id, dm.member_id) g
         WHERE dm.department_id = :id AND dm.left_at IS NULL
         GROUP BY dm.member_id, a.id, a.name
         ORDER BY a.name
    SQL);
    $st->execute(['id' => $departmentId]);
    $by = [];
    foreach ($st->fetchAll() as $r) {
        $by[(int) $r['member_id']][] = $r;
    }
    return $by;
}

function upsert_department(PDO $pdo, ?int $id, array $f): array
{
    if ($id === null) {
        $st = $pdo->prepare(<<<'SQL'
            INSERT INTO departments (name, description, parent_id, manager_member_id, home_location_id,
                                     monthly_budget_amount, budget_currency, handbook_markdown)
            VALUES (:name, :descr, :parent, :manager, :home, :budget, :cur, :handbook)
            RETURNING *
        SQL);
        $st->execute([
            'name' => $f['name'], 'descr' => $f['description'], 'parent' => $f['parent_id'],
            'manager' => $f['manager_member_id'], 'home' => $f['home_location_id'],
            'budget' => $f['monthly_budget_amount'], 'cur' => $f['budget_currency'],
            'handbook' => $f['handbook_markdown'] ?? null,
        ]);
        return $st->fetch() ?: [];
    }
    // A standing department (Front Office, HR, Accounting, Audit) may be renamed and
    // re-managed, never re-keyed or deleted — the CHECK on system_key and the protection
    // trigger in db/055 enforce that. A parent left empty is not a department floating free:
    // db/074's trigger parents it to the Front Office.
    $st = $pdo->prepare(<<<'SQL'
        UPDATE departments
           SET name = :name, description = :descr, parent_id = :parent,
               manager_member_id = :manager, home_location_id = :home,
               monthly_budget_amount = :budget, budget_currency = :cur,
               handbook_markdown = :handbook
         WHERE id = :id
        RETURNING *
    SQL);
    $st->execute([
        'name' => $f['name'], 'descr' => $f['description'], 'parent' => $f['parent_id'],
        'manager' => $f['manager_member_id'], 'home' => $f['home_location_id'],
        'budget' => $f['monthly_budget_amount'], 'cur' => $f['budget_currency'],
        'handbook' => $f['handbook_markdown'] ?? null, 'id' => $id,
    ]);
    return $st->fetch() ?: [];
}

function add_department_member(PDO $pdo, int $departmentId, int $memberId, bool $isAdmin, bool $isPrimary): array
{
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO department_members (department_id, member_id, is_admin, is_primary)
        VALUES (:d, :m, :a, :p)
        ON CONFLICT (department_id, member_id) WHERE left_at IS NULL
        DO UPDATE SET is_admin = EXCLUDED.is_admin, is_primary = EXCLUDED.is_primary, left_at = NULL
        RETURNING department_id, member_id, is_admin, is_primary
    SQL);
    $st->execute(['d' => $departmentId, 'm' => $memberId, 'a' => $isAdmin ? 't' : 'f', 'p' => $isPrimary ? 't' : 'f']);
    return $st->fetch() ?: [];
}

/**
 * Leaving a department is dated, not erased: left_at is what the schema models (the live
 * membership indexes are all partial on left_at IS NULL), so "who was in Sales in March"
 * stays answerable and re-adding the person is an update, not a second row.
 */
function remove_department_member(PDO $pdo, int $departmentId, int $memberId): bool
{
    $st = $pdo->prepare(<<<'SQL'
        UPDATE department_members
           SET left_at = now(), is_admin = false, is_primary = false
         WHERE department_id = :d AND member_id = :m AND left_at IS NULL
    SQL);
    $st->execute(['d' => $departmentId, 'm' => $memberId]);
    return $st->rowCount() > 0;
}

/** Members that can be picked as a manager or added to a department. */
function selectable_members(PDO $pdo): array
{
    return $pdo->query(<<<'SQL'
        SELECT member_id, display_name, member_kind, business_role
          FROM mcp_team_directory
         ORDER BY display_name
    SQL)->fetchAll();
}

function business_locations(PDO $pdo): array
{
    return $pdo->query('SELECT location_id, name, kind, siting, status FROM mcp_locations
                         ORDER BY kind, name')->fetchAll();
}

/**
 * Where a department works unless told otherwise: the first active onsite office. A
 * department may sit anywhere — including a rented offsite office — but the default is a
 * machine we run, which is the same rule the Front Office seed follows (db/074).
 */
function default_department_location(array $locations): ?int
{
    foreach ($locations as $l) {
        if ($l['kind'] === 'office' && $l['status'] === 'active' && $l['siting'] === 'onsite') {
            return (int) $l['location_id'];
        }
    }
    return null;
}

/**
 * Would parenting $departmentId under $parentId close a loop? The tree is rooted at the
 * Front Office, so a cycle would quietly detach a whole branch from the org chart: walk up
 * from the proposed parent and refuse if we meet the department itself.
 */
function department_would_cycle(PDO $pdo, int $departmentId, int $parentId): bool
{
    $st = $pdo->prepare(<<<'SQL'
        WITH RECURSIVE ancestors AS (
            SELECT id, parent_id FROM departments WHERE id = :parent
            UNION ALL
            SELECT d.id, d.parent_id FROM departments d JOIN ancestors a ON d.id = a.parent_id
        )
        SELECT count(*) FROM ancestors WHERE id = :dept
    SQL);
    $st->execute(['parent' => $parentId, 'dept' => $departmentId]);
    return (int) $st->fetchColumn() > 0;
}

/**
 * What still works in a department, in words — the reasons it cannot be deleted. A refusal
 * names what is in the way, so the answer is "move those first", never a bare "cannot".
 * Live memberships (people and agents), the named manager, departments reporting to it,
 * applications it owns or that serve it (a live department scope, whose foreign key has no
 * ON DELETE) and open invitations into it are attachments the delete would sever; a ledger statement line or an eval set naming it is history the delete would blank
 * (both foreign keys are ON DELETE SET NULL, and a closed statement never changes). Counted
 * from department_ties(), the rows the department page shows.
 *
 * @return string[] e.g. ["a named manager", "2 people", "1 agent"]
 */
function department_delete_blockers(PDO $pdo, int $id): array
{
    $blockers = [];
    foreach (department_ties($pdo, $id) as $tie) {
        $count = count($tie['items']);
        if (!$tie['blocks'] || $count === 0) {
            continue;
        }
        $blockers[] = $tie['key'] === 'manager' ? 'a named manager'
            : $count . ' ' . ($count === 1 ? $tie['one'] : $tie['many']);
    }
    return $blockers;
}

/**
 * Everything that names a department, each kind with its rows ({id, name, detail}) — the one
 * source for the department page's picture and for department_delete_blockers(), so what the
 * page shows and what the delete refuses never differ. `blocks` = the delete is refused while
 * any row exists (see department_delete_blockers()); the rest goes with the department
 * (department_delete_cascade()). Every kind is returned, empty or not, so the page can say "none".
 *
 * @return list<array{key:string,label:string,one:string,many:string,blocks:bool,items:list<array>}>
 */
function department_ties(PDO $pdo, int $id): array
{
    $kinds = [
        ['manager', 'Named manager', 'named manager', 'named managers', true,
            'SELECT m.id, m.display_name AS name, NULL AS detail
               FROM departments d JOIN members m ON m.id = d.manager_member_id WHERE d.id = :id'],
        ['people', 'People in it', 'person', 'people', true,
            "SELECT m.id, m.display_name AS name, CASE WHEN dm.is_admin THEN 'administers it' END AS detail
               FROM department_members dm JOIN members m ON m.id = dm.member_id
              WHERE dm.department_id = :id AND dm.left_at IS NULL AND m.member_kind = 'human' ORDER BY m.display_name"],
        ['agents', 'Agents in it', 'agent', 'agents', true,
            "SELECT m.id, m.display_name AS name, NULL AS detail
               FROM department_members dm JOIN members m ON m.id = dm.member_id
              WHERE dm.department_id = :id AND dm.left_at IS NULL AND m.member_kind = 'agent' ORDER BY m.display_name"],
        ['child_departments', 'Departments that report to it', 'department that reports to it', 'departments that report to it', true,
            'SELECT id, name::text AS name, NULL AS detail FROM departments WHERE parent_id = :id ORDER BY name'],
        ['owned_applications', 'Applications it owns', 'application it owns', 'applications it owns', true,
            "SELECT id, name, CASE WHEN status <> 'active' THEN status END AS detail
               FROM applications WHERE owner_department_id = :id ORDER BY name"],
        ['serving_applications', 'Applications that serve it', 'application that serves it', 'applications that serve it', true,
            'SELECT a.id, a.name, NULL AS detail FROM application_scopes s JOIN applications a ON a.id = s.application_id
              WHERE s.department_id = :id AND s.removed_at IS NULL ORDER BY a.name'],
        ['open_invitations', 'Open invitations into it', 'open invitation into it', 'open invitations into it', true,
            "SELECT id, email::text AS name, 'expires ' || to_char(expires_at, 'YYYY-MM-DD') AS detail
               FROM invitations WHERE department_id = :id
                AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now() ORDER BY expires_at"],
        ['ledger_lines', 'Ledger statement lines', 'ledger statement line', 'ledger statement lines', true,
            "SELECT id, to_char(period_start, 'YYYY-MM') || ' · ' || provider AS name,
                    amount::text || ' ' || currency || ' · ' || status AS detail
               FROM ai_usage_postings WHERE department_id = :id ORDER BY period_start, id"],
        ['eval_sets', 'Eval sets', 'eval set', 'eval sets', true,
            "SELECT id, name, CASE WHEN status <> 'active' THEN status END AS detail
               FROM eval_sets WHERE department_id = :id ORDER BY name"],
        ['past_memberships', 'Past members', 'past membership', 'past memberships', false,
            "SELECT m.id, m.display_name AS name, 'left ' || to_char(dm.left_at, 'YYYY-MM-DD') AS detail
               FROM department_members dm JOIN members m ON m.id = dm.member_id
              WHERE dm.department_id = :id AND dm.left_at IS NOT NULL ORDER BY dm.left_at DESC"],
        ['approval_policies', 'Approval policies', 'approval policy', 'approval policies', false,
            "SELECT id, name, CASE WHEN NOT active THEN 'inactive' END AS detail
               FROM approval_policies WHERE department_id = :id ORDER BY name"],
        ['skill_assignments', 'Skill assignments', 'skill assignment', 'skill assignments', false,
            "SELECT id, skill_name AS name, CASE WHEN revoked_at IS NOT NULL THEN 'revoked' END AS detail
               FROM skill_assignments WHERE department_id = :id ORDER BY skill_name"],
        ['access_grants', 'Application access granted to it', 'access grant', 'access grants', false,
            "SELECT a.id, a.name, COALESCE(ac.role_key, ac.capability)
                    || CASE WHEN ac.revoked_at IS NOT NULL THEN ' · revoked'
                            WHEN ac.expires_at <= now() THEN ' · expired' ELSE '' END AS detail
               FROM application_access ac JOIN applications a ON a.id = ac.application_id
              WHERE ac.department_id = :id ORDER BY ac.revoked_at NULLS FIRST, a.name"],
    ];
    $ties = [];
    foreach ($kinds as [$key, $label, $one, $many, $blocks, $sql]) {
        $st = $pdo->prepare($sql);
        $st->execute(['id' => $id]);
        $ties[] = ['key' => $key, 'label' => $label, 'one' => $one, 'many' => $many, 'blocks' => $blocks,
                   'items' => $st->fetchAll()];
    }
    return $ties;
}

/**
 * What goes with the row when it is deleted (ON DELETE CASCADE): its past memberships, its
 * approval policies, its skill assignments and its application access grants. None of them
 * blocks the delete — they are the department's own configuration and its dated history of
 * who once belonged — but the activity log records the counts, since afterwards nothing
 * else will say they existed.
 *
 * @return array<string,int>
 */
function department_delete_cascade(PDO $pdo, int $id): array
{
    $counts = [];
    foreach (['past_memberships' => ['department_members', 'AND left_at IS NOT NULL'],
              'approval_policies' => ['approval_policies', ''],
              'skill_assignments' => ['skill_assignments', ''],
              'application_access_grants' => ['application_access', '']] as $key => [$table, $extra]) {
        $st = $pdo->prepare("SELECT count(*) FROM {$table} WHERE department_id = :id {$extra}");
        $st->execute(['id' => $id]);
        $counts[$key] = (int) $st->fetchColumn();
    }
    return $counts;
}

/**
 * Delete a department outright — the super-admin's remedy for one nothing works in. The four
 * standing departments are never deleted (db/055's trigger raises; refused here first by
 * name), and anything still attached is refused by name instead of severed.
 *
 * @throws RuntimeException naming what is in the way.
 */
function delete_department(PDO $pdo, int $id): bool
{
    $department = find_department($pdo, $id);
    if ($department === null) {
        return false;
    }
    if (!empty($department['is_system'])) {
        throw new RuntimeException($department['name'] . ' is a standing department: every business has it, and it is never deleted.');
    }
    $blockers = department_delete_blockers($pdo, $id);
    if ($blockers !== []) {
        throw new RuntimeException(
            'This department cannot be deleted — it still has ' . implode(', ', $blockers)
            . '. Move or remove those first.'
        );
    }
    $st = $pdo->prepare('DELETE FROM departments WHERE id = :id AND NOT is_system');
    $st->execute(['id' => $id]);
    return $st->rowCount() > 0;
}

// ---- business settings ----------------------------------------------------

function update_business_settings(PDO $pdo, array $f): array
{
    $st = $pdo->prepare(<<<'SQL'
        UPDATE business_settings
           SET business_name = :name, legal_name = :legal, base_currency = :cur, timezone = :tz,
               fiscal_year_start_month = :fy, default_payment_terms_days = :terms,
               deal_quiet_days = :quiet, prompt_payload_retention_days = :retention,
               default_hourly_rate = :rate
         WHERE id = 1
        RETURNING *
    SQL);
    $st->execute([
        'name' => $f['business_name'], 'legal' => $f['legal_name'], 'cur' => $f['base_currency'],
        'tz' => $f['timezone'], 'fy' => $f['fiscal_year_start_month'], 'terms' => $f['default_payment_terms_days'],
        'quiet' => $f['deal_quiet_days'], 'retention' => $f['prompt_payload_retention_days'],
        'rate' => $f['default_hourly_rate'] ?? null,
    ]);
    return $st->fetch() ?: [];
}
