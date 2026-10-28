<?php
declare(strict_types=1);

/**
 * The directory API (A4, 2026-09-22 — docs/business-os-integration.md, "The directory API";
 * docs/build-specs/kernel-directory-api.md). The kernel owns who exists, their role and status,
 * and their departments; an application from us keeps a mirror with the kernel's ids and, when
 * it is HR, changes the directory here — never through shared tables.
 *
 * Served on the internal port only (html/api/v1/directory/*), never on a public name. Every call
 * carries the application's own bearer token; a write also names the person making it in
 * X-Acting-Member, and it is THAT person's rights — the people rule, admin-of-department — that
 * decide, exactly as on a kernel screen. Every write logs with source 'application', the
 * application's key and the acting member.
 */
require_once dirname(__DIR__) . '/features/team/queries.php';

const DIRECTORY_SCHEMA = 'os.directory/1';
const DIRECTORY_CHANGES_SCHEMA = 'os.directory-changes/1';
const DIRECTORY_OVERLAP_SECONDS = 10;    // a change committed late is delivered again; the mirror upserts

/**
 * The application behind the bearer token, or 401 with one sentence whatever the reason. Reads
 * run as the super-admin who minted the token: the directory is handed over as the kernel sees it.
 */
function directory_authenticate(): array
{
    $pdo = db();
    $token = api_bearer_token();
    if ($token === '') {
        api_error('unauthorized', 'A valid application token is required.', 401);
    }
    $st = $pdo->prepare(<<<'SQL'
        SELECT t.id AS token_id, t.member_id, a.id AS application_id, a.app_key, a.name, a.status, a.directory_writes
          FROM mcp_access_tokens t
          JOIN applications a ON a.id = t.application_id
         WHERE t.token_hash = :h AND t.scope = 'application' AND t.revoked_at IS NULL
           AND (t.expires_at IS NULL OR t.expires_at > now())
    SQL);
    $st->execute(['h' => hash('sha256', $token)]);
    $row = $st->fetch();
    if ($row === false || !in_array($row['status'], ['active', 'degraded'], true)) {
        error_log('directory auth: token rejected (missing, revoked, expired, or the application is not active)');
        api_error('unauthorized', 'A valid application token is required.', 401);
    }
    $minter = find_member_by_id($pdo, (int) $row['member_id']);
    if ($minter === null || $minter['status'] !== 'active' || ($minter['business_role'] ?? '') !== 'super_admin') {
        error_log('directory auth: the token\'s minter is no longer an active super-admin');
        api_error('unauthorized', 'A valid application token is required.', 401);
    }
    $pdo->prepare('UPDATE mcp_access_tokens SET last_used_at = now() WHERE id = :id')->execute(['id' => $row['token_id']]);
    $_SESSION['member_id'] = (int) $minter['id'];
    $_SESSION['member_role'] = $minter['role'];
    db_apply_context($pdo);
    $application = ['id' => (int) $row['application_id'], 'app_key' => (string) $row['app_key'],
        'name' => (string) $row['name'], 'directory_writes' => !empty($row['directory_writes'])];
    $GLOBALS['__directory_application'] = $application;
    return $application;
}

function directory_application(): array
{
    return $GLOBALS['__directory_application'];
}

/** The request body: JSON when it says so, else a form (PATCH and DELETE bodies included). */
function directory_body(): array
{
    $type = strtolower((string) ($_SERVER['CONTENT_TYPE'] ?? ''));
    if (str_starts_with($type, 'application/json')) {
        $body = json_decode((string) file_get_contents('php://input'), true);
        return is_array($body) ? $body : [];
    }
    if ($_POST !== []) {
        return $_POST;
    }
    parse_str((string) file_get_contents('php://input'), $body);
    return is_array($body) ? $body : [];
}

function directory_method(): string
{
    return strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));
}

/**
 * Who is making a write: the person named in X-Acting-Member — an active human with a live
 * grant on this application — and the application must have declared directory writes. From
 * here the database context is that person's, so every rule below is theirs.
 */
function directory_acting_member(PDO $pdo): array
{
    $app = directory_application();
    if (!$app['directory_writes']) {
        api_error('forbidden', 'This application is not registered to change the directory (maludb-os.json directory.writes).', 403);
    }
    return application_acting_member($pdo);
}

/**
 * The person an application is acting for (X-Acting-Member): an active human with a live grant on
 * the application. The database context becomes theirs. Shared by the directory's writes and the
 * chat endpoint (A6).
 */
function application_acting_member(PDO $pdo): array
{
    $app = directory_application();
    $id = (int) ($_SERVER['HTTP_X_ACTING_MEMBER'] ?? 0);
    if ($id <= 0) {
        api_error('invalid', 'X-Acting-Member names the person making this change.', 400);
    }
    $member = find_member_by_id($pdo, $id);
    if ($member === null || $member['status'] !== 'active' || ($member['member_kind'] ?? 'human') !== 'human') {
        api_error('forbidden', 'The acting member must be an active person.', 403);
    }
    $_SESSION['member_id'] = (int) $member['id'];
    $_SESSION['member_role'] = $member['role'];
    db_apply_context($pdo);
    $st = $pdo->prepare('SELECT app_can_use_application(:a)');
    $st->execute(['a' => $app['id']]);
    if (!$st->fetchColumn()) {
        api_error('forbidden', 'The acting member holds no live grant on this application.', 403);
    }
    return $member;
}

/** One SQL rule, asked as the acting member; refused in the given words. */
function directory_require(PDO $pdo, string $sql, array $args, string $refusal): void
{
    $st = $pdo->prepare($sql);
    $st->execute($args);
    if (!$st->fetchColumn()) {
        api_error('forbidden', $refusal, 403);
    }
}

function directory_log(PDO $pdo, string $action, string $entityType, ?int $entityId, array $extra = []): void
{
    $app = directory_application();
    $extra['after'] = ($extra['after'] ?? []) + ['via_application' => $app['app_key']];
    log_activity($pdo, $action, $entityType, $entityId, $extra + ['source' => 'application']);
}

// --------------------------------------------------------------------------
// Rows — whitelists. Never the members row (password hash, TOTP secret live there).
// --------------------------------------------------------------------------
function directory_member_row(array $m, array $departments = []): array
{
    return [
        'id' => (int) $m['id'],
        'display_name' => (string) $m['display_name'],
        'email' => (string) $m['email'],
        'member_kind' => (string) ($m['member_kind'] ?? 'human'),
        'business_role' => (string) ($m['business_role'] ?? 'user'),
        'is_external' => !empty($m['is_external']),
        'status' => (string) $m['status'],
        'job_title' => ($m['job_title'] ?? '') !== '' ? (string) $m['job_title'] : null,
        'phone' => ($m['phone'] ?? '') !== '' ? (string) $m['phone'] : null,
        'timezone' => (string) ($m['timezone'] ?? 'UTC'),
        'departments' => $departments,
        'updated_at' => json_ts($m['updated_at'] ?? null),
    ];
}

function directory_department_row(array $d): array
{
    return [
        'id' => (int) $d['id'],
        'name' => (string) $d['name'],
        'description' => ($d['description'] ?? '') !== '' ? (string) $d['description'] : null,
        'parent_id' => isset($d['parent_id']) ? (int) $d['parent_id'] : null,
        'manager_member_id' => isset($d['manager_member_id']) ? (int) $d['manager_member_id'] : null,
        'is_system' => !empty($d['is_system']),
        'system_key' => $d['system_key'] ?? null,
        'archived_at' => json_ts($d['archived_at'] ?? null),
        'updated_at' => json_ts($d['updated_at'] ?? null),
    ];
}

function directory_membership_row(array $dm): array
{
    return [
        'member_id' => (int) $dm['member_id'],
        'department_id' => (int) $dm['department_id'],
        'is_admin' => !empty($dm['is_admin']),
        'is_primary' => !empty($dm['is_primary']),
        'joined_at' => json_ts($dm['joined_at'] ?? null),
        'left_at' => json_ts($dm['left_at'] ?? null),
    ];
}

/** Members (all kinds, every status — a deactivation is what the mirror needs most), with their live departments. */
function directory_members(PDO $pdo, ?string $since = null): array
{
    $where = $since !== null ? 'WHERE m.updated_at > :since' : '';
    $st = $pdo->prepare("SELECT m.id, m.display_name, m.email, m.member_kind, m.business_role, m.is_external, m.status,
                                m.job_title, m.phone, m.timezone, m.updated_at
                           FROM members m {$where} ORDER BY m.id");
    $st->execute($since !== null ? ['since' => $since] : []);
    $members = $st->fetchAll();
    if ($members === []) {
        return [];
    }
    $ids = array_map(static fn (array $m): int => (int) $m['id'], $members);
    $in = implode(',', array_fill(0, count($ids), '?'));
    $dm = $pdo->prepare("SELECT dm.member_id, dm.department_id, d.name, dm.is_admin, dm.is_primary
                           FROM department_members dm JOIN departments d ON d.id = dm.department_id
                          WHERE dm.left_at IS NULL AND dm.member_id IN ({$in}) ORDER BY dm.is_primary DESC, d.name");
    $dm->execute($ids);
    $byMember = [];
    foreach ($dm->fetchAll() as $row) {
        $byMember[(int) $row['member_id']][] = ['id' => (int) $row['department_id'], 'name' => (string) $row['name'],
            'is_admin' => !empty($row['is_admin']), 'is_primary' => !empty($row['is_primary'])];
    }
    return array_map(static fn (array $m): array => directory_member_row($m, $byMember[(int) $m['id']] ?? []), $members);
}

function directory_departments(PDO $pdo, ?string $since = null): array
{
    $where = $since !== null ? 'WHERE updated_at > :since' : '';
    $st = $pdo->prepare("SELECT id, name, description, parent_id, manager_member_id, is_system, system_key, archived_at, updated_at
                           FROM departments {$where} ORDER BY id");
    $st->execute($since !== null ? ['since' => $since] : []);
    return array_map('directory_department_row', $st->fetchAll());
}

/**
 * Departments deleted since the cursor (every one ever, on a full answer), from the activity
 * log — the only place a deleted row still has a name. The mirror drops the row by id.
 */
function directory_deleted_departments(PDO $pdo, ?string $since = null): array
{
    $where = $since !== null ? 'AND occurred_at > :since' : '';
    $st = $pdo->prepare("SELECT entity_id, before->>'name' AS name, occurred_at
                           FROM activity_log
                          WHERE action = 'department.delete' AND entity_type = 'department' {$where}
                          ORDER BY occurred_at, id");
    $st->execute($since !== null ? ['since' => $since] : []);
    return array_map(static fn (array $r): array => [
        'id' => (int) $r['entity_id'],
        'name' => $r['name'] !== null ? (string) $r['name'] : null,
        'deleted_at' => json_ts($r['occurred_at']),
    ], $st->fetchAll());
}

/** Memberships, live and left (left_at set): the mirror removes what has left. */
function directory_memberships(PDO $pdo, ?string $since = null): array
{
    $where = $since !== null ? 'WHERE updated_at > :since' : 'WHERE left_at IS NULL';
    $st = $pdo->prepare("SELECT member_id, department_id, is_admin, is_primary, joined_at, left_at
                           FROM department_members {$where} ORDER BY department_id, member_id");
    $st->execute($since !== null ? ['since' => $since] : []);
    return array_map('directory_membership_row', $st->fetchAll());
}

function directory_find_member(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT id, display_name, email, member_kind, business_role, is_external, status, job_title, phone, timezone, updated_at FROM members WHERE id = :id');
    $st->execute(['id' => $id]);
    return $st->fetch() ?: null;
}

// ---- scoped applications (db/141 — docs/build-specs/kernel-scoped-applications.md) -------------------

/**
 * The calling application's scopes: the sites or departments it serves. Since the cursor: every scope
 * added, removed (removed_at set), or whose site or department changed. Full: every live scope.
 */
function directory_scopes(PDO $pdo, int $applicationId, ?string $since = null): array
{
    $where = $since !== null
        ? 'AND (s.updated_at > :since OR l.updated_at > :since OR d.updated_at > :since)'
        : 'AND s.removed_at IS NULL';
    $st = $pdo->prepare("SELECT s.id, s.location_id, s.department_id, COALESCE(l.name, d.name::text) AS name,
                                l.address, l.timezone, s.removed_at,
                                GREATEST(s.updated_at, l.updated_at, d.updated_at) AS updated_at
                           FROM application_scopes s
                           LEFT JOIN locations l ON l.id = s.location_id
                           LEFT JOIN departments d ON d.id = s.department_id
                          WHERE s.application_id = :app {$where}
                          ORDER BY s.id");
    $st->execute(['app' => $applicationId] + ($since !== null ? ['since' => $since] : []));
    return array_map(static fn (array $r): array => [
        'scope_id' => (int) $r['id'],
        'kind' => $r['location_id'] !== null ? 'location' : 'department',
        'location_id' => $r['location_id'] !== null ? (int) $r['location_id'] : null,
        'department_id' => $r['department_id'] !== null ? (int) $r['department_id'] : null,
        'name' => (string) $r['name'],
        'address' => $r['address'],
        'timezone' => $r['timezone'],
        'removed_at' => $r['removed_at'] !== null ? json_ts($r['removed_at']) : null,
        'updated_at' => json_ts($r['updated_at']),
    ], $st->fetchAll());
}

/**
 * What members hold on the calling application: one row per member, their WHOLE holding, replacing
 * what the mirror had (`capability` null and `scopes` [] = they hold nothing now — drop their access).
 * Full: everyone who holds anything. Since the cursor: everyone whose holding may have changed — a
 * grant granted, revoked or expired, a scope removed (each expanded to every member it reaches, through
 * a department or a residency, now or before), and, among the members any grant of this application
 * ever reached, anyone whose status, memberships or residencies changed. Super-admins hold everything,
 * so they are in whenever a scope changed.
 */
function directory_access(PDO $pdo, int $applicationId, ?string $since = null): array
{
    require_once dirname(__DIR__) . '/features/applications/sso.php';
    if ($since === null) {
        $st = $pdo->prepare(<<<'SQL'
            SELECT ac.member_id AS id FROM application_access ac
             WHERE ac.application_id = :app AND ac.revoked_at IS NULL AND ac.member_id IS NOT NULL
            UNION SELECT dm.member_id FROM application_access ac
              JOIN department_members dm ON dm.department_id = ac.department_id AND dm.left_at IS NULL
             WHERE ac.application_id = :app AND ac.revoked_at IS NULL
            UNION SELECT r.member_id FROM application_access ac
              JOIN location_residents r ON r.location_id = ac.resident_location_id AND r.removed_at IS NULL
             WHERE ac.application_id = :app AND ac.revoked_at IS NULL
            UNION SELECT m.id FROM members m WHERE m.business_role = 'super_admin' AND m.status = 'active'
        SQL);
        $st->execute(['app' => $applicationId]);
    } else {
        $st = $pdo->prepare(<<<'SQL'
            WITH changed_scopes AS (
                SELECT id FROM application_scopes WHERE application_id = :app AND updated_at > :since
            ), changed_grants AS (
                SELECT * FROM application_access ac
                 WHERE ac.application_id = :app
                   AND (ac.granted_at > :since OR ac.revoked_at > :since
                        OR (ac.expires_at > :since AND ac.expires_at <= now())
                        OR ac.scope_id IN (SELECT id FROM changed_scopes))
            ), reach AS (            -- every member any grant of this application ever reached
                SELECT ac.member_id AS id FROM application_access ac WHERE ac.application_id = :app AND ac.member_id IS NOT NULL
                UNION SELECT dm.member_id FROM application_access ac JOIN department_members dm ON dm.department_id = ac.department_id
                 WHERE ac.application_id = :app
                UNION SELECT r.member_id FROM application_access ac JOIN location_residents r ON r.location_id = ac.resident_location_id
                 WHERE ac.application_id = :app
            )
            SELECT g.member_id AS id FROM changed_grants g WHERE g.member_id IS NOT NULL
            UNION SELECT dm.member_id FROM changed_grants g JOIN department_members dm ON dm.department_id = g.department_id
            UNION SELECT r.member_id FROM changed_grants g JOIN location_residents r ON r.location_id = g.resident_location_id
            UNION SELECT m.id FROM members m WHERE m.updated_at > :since AND m.id IN (SELECT id FROM reach)
            UNION SELECT dm.member_id FROM department_members dm WHERE dm.updated_at > :since AND dm.member_id IN (SELECT id FROM reach)
            UNION SELECT r.member_id FROM location_residents r
             WHERE (r.added_at > :since OR r.removed_at > :since) AND r.member_id IN (SELECT id FROM reach)
            UNION SELECT m.id FROM members m WHERE m.business_role = 'super_admin'
               AND (m.updated_at > :since OR EXISTS (SELECT 1 FROM changed_scopes))
            -- db/145: the roles were read again from the application — what they give may have
            -- changed, so every holder's rights go out again.
            UNION SELECT id FROM reach
             WHERE EXISTS (SELECT 1 FROM applications a WHERE a.id = :app AND a.roles_synced_at > :since)
            UNION SELECT m.id FROM members m WHERE m.business_role = 'super_admin' AND m.status = 'active'
               AND EXISTS (SELECT 1 FROM applications a WHERE a.id = :app AND a.roles_synced_at > :since)
        SQL);
        $st->execute(['app' => $applicationId, 'since' => $since]);
    }
    $rows = [];
    foreach (array_map('intval', array_column($st->fetchAll(), 'id')) as $memberId) {
        $h = sso_member_holding($pdo, $applicationId, $memberId);
        if ($since === null && $h['capability'] === null) {
            continue;                       // a full answer lists holders only
        }
        $rows[] = ['member_id' => $memberId, 'role' => $h['role'], 'capability' => $h['capability'],
                   'scopes' => array_map(static fn (array $s): array => [
                       'scope_id' => $s['scope_id'], 'role' => $s['role'], 'capability' => $s['capability'],
                       'roles' => $s['roles'], 'rights' => $s['rights'],
                   ], $h['scopes']),
                   // db/145, additive: every role held and the rights they give.
                   'roles' => $h['roles'], 'rights' => $h['rights']];
    }
    usort($rows, static fn (array $a, array $b): int => $a['member_id'] <=> $b['member_id']);
    return $rows;
}
