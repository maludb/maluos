<?php
declare(strict_types=1);

/**
 * The estate: buildings, offices and desks (build spec: docs/build-specs/estate.md).
 *
 * Reads come from the mcp_* views; writes go to base tables, as the Contacts exemplar and
 * every later slice established. Two things this file must NOT do, because the database
 * already guarantees them (db/043_locations_task_queue.sql):
 *   - re-check that a desk has an owner, or that a building has no parent (CHECK constraints
 *     locations_desk_has_owner / locations_building_is_root do that; a violation surfaces as a
 *     PDOException the endpoint turns into a field error);
 *   - re-implement `name` uniqueness (a plain UNIQUE index; same handling).
 *
 * A location is never department-stamped: `locations` has no department_id. A location HOSTS
 * departments (`departments.home_location_id`), it is not owned by one.
 */

const LOCATION_PAGE_SIZE = 25;
const LOCATION_SORT_ALLOWED = ['name', 'kind', 'last_seen_at'];
const LOCATION_KINDS = ['building', 'office', 'desk', 'site'];
/**
 * What kind of machine a location is. Revised by db/069: the old list (proxmox, kvm, lxc,
 * bare_metal, cloud, workstation, other) named products and categories interchangeably and did
 * not answer the question an operator asks, which is "what kind of machine is this?".
 * Keys are stored; the labels are what a person reads.
 */
const LOCATION_PLATFORMS = ['physical_hypervisor', 'physical_os', 'vps', 'desktop', 'laptop'];
const LOCATION_PLATFORM_LABELS = [
    'physical_hypervisor' => 'Physical Server with Hypervisor',
    'physical_os'         => 'Physical Server with OS',
    'vps'                 => 'Virtual Private Server',
    'desktop'             => 'Desktop',
    'laptop'              => 'Laptop',
];
const LOCATION_SITINGS = ['onsite', 'offsite'];

// --------------------------------------------------------------------------
// Lists
// --------------------------------------------------------------------------
function find_locations(PDO $pdo, array $filters, string $sort = 'kind', int $page = 1): array
{
    $sort = in_array($sort, LOCATION_SORT_ALLOWED, true) ? $sort : 'kind';
    $orderBy = match ($sort) {
        'name' => 'l.name ASC',
        'last_seen_at' => 'l.last_seen_at DESC NULLS LAST, l.name ASC',
        // Hierarchy order, not alphabetical: a table of the estate reads building, office,
        // desk. Sorting on the kind text would put desks above offices.
        default => "CASE l.kind WHEN 'building' THEN 1 WHEN 'office' THEN 2 ELSE 3 END, l.name ASC",
    };
    [$where, $params] = location_filter_sql($filters);
    $offset = (max(1, $page) - 1) * LOCATION_PAGE_SIZE;

    $st = $pdo->prepare("
        SELECT l.*, count(*) OVER() AS total_count
          FROM mcp_locations l
          {$where}
         ORDER BY {$orderBy}
         LIMIT :lim OFFSET :off
    ");
    foreach ($params as $key => $value) {
        $st->bindValue($key, $value);
    }
    $st->bindValue('lim', LOCATION_PAGE_SIZE, PDO::PARAM_INT);
    $st->bindValue('off', $offset, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}

/** @return array{0: string, 1: array} the WHERE clause and its bound values */
function location_filter_sql(array $filters): array
{
    $where = [];
    $params = [];

    if (($filters['kind'] ?? '') !== '') {
        $where[] = 'l.kind = :kind';
        $params['kind'] = $filters['kind'];
    }
    if (($filters['parent_location_id'] ?? null) !== null) {
        $where[] = 'l.parent_location_id = :parent';
        $params['parent'] = (int) $filters['parent_location_id'];
    }
    if (!empty($filters['online'])) {
        $where[] = "l.presence = 'online'";
    }
    // Retired locations are hidden unless status=retired is asked for.
    if (($filters['status'] ?? '') === 'retired') {
        $where[] = "l.status = 'retired'";
    } else {
        $where[] = "l.status = 'active'";
    }
    return [$where === [] ? '' : 'WHERE ' . implode(' AND ', $where), $params];
}

// --------------------------------------------------------------------------
// Single records
// --------------------------------------------------------------------------
function find_location(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('
        SELECT l.*, td.display_name AS office_manager_name
          FROM mcp_locations l
          LEFT JOIN mcp_team_directory td ON td.member_id = l.office_manager_member_id
         WHERE l.location_id = :id
    ');
    $st->execute(['id' => $id]);
    if (($row = $st->fetch()) === false) {
        return null;
    }
    return $row;
}

// --------------------------------------------------------------------------
// Writes
// --------------------------------------------------------------------------
function insert_location(PDO $pdo, array $f): array
{
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO locations
            (name, kind, parent_location_id, description, owner_member_id, platform,
             external_ref, hostname, ip_address, cpu_cores, memory_mb, storage_gb, is_always_on,
             siting, operating_system, os_version, ssh_access, root_access, address, timezone)
        VALUES
            (:name, :kind, :parent, :description, :owner, :platform,
             :external_ref, :hostname, :ip, :cpu, :memory, :storage, :always_on,
             :siting, :operating_system, :os_version, :ssh_access, :root_access, :address, :timezone)
        RETURNING id
    SQL);
    $st->execute(location_params($f));
    $row = $st->fetch();
    return $row === false ? [] : (find_location($pdo, (int) $row['id']) ?? []);
}

/** `kind` is read-only on edit — a desk does not become a building. */
function update_location(PDO $pdo, int $id, array $f): array
{
    $st = $pdo->prepare(<<<'SQL'
        UPDATE locations
           SET name = :name, description = :description, owner_member_id = :owner,
               platform = :platform, external_ref = :external_ref, hostname = :hostname,
               ip_address = :ip, cpu_cores = :cpu, memory_mb = :memory, storage_gb = :storage,
               is_always_on = :always_on, siting = :siting,
               operating_system = :operating_system, os_version = :os_version,
               ssh_access = :ssh_access, root_access = :root_access,
               address = :address, timezone = :timezone, updated_at = now()
         WHERE id = :id
        RETURNING id
    SQL);
    $params = location_params($f);
    unset($params['kind'], $params['parent']);
    $params['id'] = $id;
    $st->execute($params);
    $row = $st->fetch();
    return $row === false ? [] : (find_location($pdo, $id) ?? []);
}

function location_params(array $f): array
{
    return [
        'operating_system' => $f['operating_system'] ?? null,
        'os_version' => $f['os_version'] ?? null,
        // NULL stays NULL: "not recorded" is a real answer and must not be stored as "no".
        'ssh_access' => isset($f['ssh_access']) && $f['ssh_access'] !== null
            ? ($f['ssh_access'] ? 't' : 'f') : null,
        'root_access' => isset($f['root_access']) && $f['root_access'] !== null
            ? ($f['root_access'] ? 't' : 'f') : null,
        'name' => $f['name'],
        'kind' => $f['kind'],
        'address' => $f['address'] ?? null,
        'timezone' => $f['timezone'] ?? null,
        'parent' => $f['parent_location_id'] ?? null,
        'description' => $f['description'] ?? null,
        'owner' => $f['owner_member_id'] ?? null,
        'platform' => $f['platform'] ?? null,
        'external_ref' => $f['external_ref'] ?? null,
        'hostname' => $f['hostname'] ?? null,
        'ip' => $f['ip_address'] ?? null,
        'cpu' => $f['cpu_cores'] ?? null,
        'memory' => $f['memory_mb'] ?? null,
        'storage' => $f['storage_gb'] ?? null,
        'always_on' => !empty($f['is_always_on']) ? 't' : 'f',
        'siting' => $f['siting'] ?? null,
    ];
}

function move_location(PDO $pdo, int $id, ?int $parentId): array
{
    $st = $pdo->prepare('UPDATE locations SET parent_location_id = :parent, updated_at = now()
                          WHERE id = :id RETURNING id');
    $st->execute(['parent' => $parentId, 'id' => $id]);
    $row = $st->fetch();
    return $row === false ? [] : (find_location($pdo, $id) ?? []);
}

function rename_location(PDO $pdo, int $id, string $name): array
{
    $st = $pdo->prepare('UPDATE locations SET name = :name, updated_at = now()
                          WHERE id = :id RETURNING id');
    $st->execute(['name' => $name, 'id' => $id]);
    $row = $st->fetch();
    return $row === false ? [] : (find_location($pdo, $id) ?? []);
}

/**
 * Refuses and NAMES what is in the way — the manifest's own wording: "a building or office is
 * never retired while it still has active children, applications or resident members; the
 * endpoint refuses and names them." That list is the user's next task, not a generic refusal.
 *
 * Reads the base tables directly rather than the mcp_* views: this is a system check on behalf
 * of whoever holds the locations grant, not a personal view of the business (the same reasoning
 * archive_gl_account() uses reading gl_accounts directly for its balance check, and the posting
 * run uses reading source documents directly — Books review finding 4).
 */
function retire_location(PDO $pdo, int $id): array
{
    $st = $pdo->prepare("SELECT name FROM locations WHERE parent_location_id = :id AND status = 'active' ORDER BY name");
    $st->execute(['id' => $id]);
    $children = $st->fetchAll(PDO::FETCH_COLUMN);

    $st = $pdo->prepare('SELECT name FROM applications WHERE location_id = :id AND retired_at IS NULL ORDER BY name');
    $st->execute(['id' => $id]);
    $apps = $st->fetchAll(PDO::FETCH_COLUMN);

    $st = $pdo->prepare("
        SELECT m.display_name FROM location_residents r
          JOIN members m ON m.id = r.member_id
         WHERE r.location_id = :id AND r.removed_at IS NULL
         ORDER BY m.display_name
    ");
    $st->execute(['id' => $id]);
    $residents = $st->fetchAll(PDO::FETCH_COLUMN);

    if ($children !== [] || $apps !== [] || $residents !== []) {
        $parts = [];
        if ($children !== []) {
            $parts[] = 'still holds: ' . implode(', ', $children);
        }
        if ($apps !== []) {
            $parts[] = 'still hosts: ' . implode(', ', $apps);
        }
        if ($residents !== []) {
            $parts[] = 'still has residents: ' . implode(', ', $residents);
        }
        throw new RuntimeException('This location cannot be retired yet — ' . implode('; ', $parts) . '.');
    }

    $st = $pdo->prepare("UPDATE locations SET status = 'retired', retired_at = now(), updated_at = now()
                          WHERE id = :id AND status = 'active' RETURNING id");
    $st->execute(['id' => $id]);
    $row = $st->fetch();
    return $row === false ? [] : (find_location($pdo, $id) ?? []);
}

/**
 * What still points at this location, in words. A location is referenced from sixteen places,
 * and all but three of those foreign keys are NO ACTION or RESTRICT — a raw DELETE would come
 * back as a Postgres constraint name, which tells the super-admin nothing about what to do
 * next. So the blockers are read first and named (the estate rule: a refusal says what is in
 * the way, never just "cannot").
 *
 * The three that cascade are deliberate and not blockers on their own: past residency rows
 * (`location_residents.removed_at IS NOT NULL`), consent grants, and desk imports belong to the
 * location and go with it. Its activity trail does not: `activity_log` holds no foreign key to
 * `locations`, so everything that was ever done here stays answerable after the row is gone.
 */
function location_delete_blockers(PDO $pdo, int $id): array
{
    $checks = [
        ['locations', 'parent_location_id', 'locations inside it', ''],
        ['location_residents', 'location_id', 'residents', 'AND removed_at IS NULL'],
        ['departments', 'home_location_id', 'departments that call it home', 'AND archived_at IS NULL'],
        ['applications', 'location_id', 'applications installed here', ''],
        ['agent_profiles', 'home_location_id', 'agents that live here', ''],
        ['agent_duties', 'location_id', 'agent duties scheduled here', ''],
        ['agent_runs', 'location_id', 'recorded agent runs', ''],
        ['prompt_ledger', 'location_id', 'prompt-ledger entries', ''],
        ['location_tasks', 'target_location_id', 'tasks sent to it', ''],
        ['location_tasks', 'requester_location_id', 'tasks it asked for', ''],
        // documents, employment_profiles and stock_locations went with the kernel cut (db/133).
        ['application_scopes', 'location_id', 'applications serving it', 'AND removed_at IS NULL'],
        ['application_access', 'resident_location_id', 'access grants to everyone there', 'AND revoked_at IS NULL'],
    ];

    $blockers = [];
    foreach ($checks as [$table, $column, $label, $extra]) {
        $st = $pdo->prepare("SELECT count(*) FROM {$table} WHERE {$column} = :id {$extra}");
        $st->execute(['id' => $id]);
        $count = (int) $st->fetchColumn();
        if ($count > 0) {
            $blockers[] = $count . ' ' . $label;
        }
    }
    return $blockers;
}

/**
 * Delete a location outright — the super-admin's remedy for a row that should never have
 * existed, which retiring only hides. Anything with history attached is refused instead:
 * retire that one, so what happened there stays readable.
 *
 * @throws RuntimeException naming what still points at it.
 */
function delete_location(PDO $pdo, int $id): bool
{
    $blockers = location_delete_blockers($pdo, $id);
    if ($blockers !== []) {
        throw new RuntimeException(
            'This location cannot be deleted — it still has ' . implode(', ', $blockers)
            . '. Move or remove those first, or retire the location instead, which keeps it '
            . 'and its history.'
        );
    }

    $st = $pdo->prepare('DELETE FROM locations WHERE id = :id');
    $st->execute(['id' => $id]);
    return $st->rowCount() > 0;
}

/** office_manager_member_id references agent_profiles(member_id) — an invalid pick surfaces as
 *  a foreign-key PDOException the endpoint turns into a field error. */
function set_office_manager(PDO $pdo, int $id, ?int $agentMemberId): array
{
    $st = $pdo->prepare("UPDATE locations SET office_manager_member_id = :agent, updated_at = now()
                          WHERE id = :id AND kind = 'office' RETURNING id");
    $st->execute(['agent' => $agentMemberId, 'id' => $id]);
    $row = $st->fetch();
    return $row === false ? [] : (find_location($pdo, $id) ?? []);
}

// --------------------------------------------------------------------------
// Residents
// --------------------------------------------------------------------------
function find_location_residents(PDO $pdo, int $id): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_location_residents WHERE location_id = :id
                          ORDER BY is_primary DESC, member_name');
    $st->execute(['id' => $id]);
    return $st->fetchAll();
}

function add_location_resident(PDO $pdo, int $id, int $memberId, bool $isPrimary): array
{
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO location_residents (location_id, member_id, is_primary)
        VALUES (:loc, :member, :primary)
        ON CONFLICT (location_id, member_id) WHERE removed_at IS NULL
        DO UPDATE SET is_primary = EXCLUDED.is_primary
        RETURNING location_id, member_id, is_primary
    SQL);
    $st->execute(['loc' => $id, 'member' => $memberId, 'primary' => $isPrimary ? 't' : 'f']);
    return $st->fetch() ?: [];
}

function remove_location_resident(PDO $pdo, int $id, int $memberId): bool
{
    $st = $pdo->prepare('UPDATE location_residents SET removed_at = now()
                          WHERE location_id = :loc AND member_id = :member AND removed_at IS NULL');
    $st->execute(['loc' => $id, 'member' => $memberId]);
    return $st->rowCount() > 0;
}

// --------------------------------------------------------------------------
// Departments hosted here
// --------------------------------------------------------------------------
function find_location_departments(PDO $pdo, int $id): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_departments WHERE home_location_id = :id AND archived_at IS NULL
                          ORDER BY name');
    $st->execute(['id' => $id]);
    return $st->fetchAll();
}

function set_department_home(PDO $pdo, int $departmentId, ?int $locationId): array
{
    $st = $pdo->prepare('UPDATE departments SET home_location_id = :loc, updated_at = now()
                          WHERE id = :dept RETURNING id');
    $st->execute(['loc' => $locationId, 'dept' => $departmentId]);
    if ($st->fetch() === false) {
        return [];
    }
    $st2 = $pdo->prepare('SELECT * FROM mcp_departments WHERE department_id = :id');
    $st2->execute(['id' => $departmentId]);
    return $st2->fetch() ?: [];
}

// --------------------------------------------------------------------------
// Applications residing here (read-only — the Applications module owns their CRUD)
// --------------------------------------------------------------------------
function find_location_applications(PDO $pdo, int $id): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_applications WHERE location_id = :id AND retired_at IS NULL
                          ORDER BY name');
    $st->execute(['id' => $id]);
    return $st->fetchAll();
}

/** The scoped applications that serve a site (db/141) — a site runs nothing itself. */
function find_location_serving_applications(PDO $pdo, int $id): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_application_scopes WHERE location_id = :id ORDER BY application_name');
    $st->execute(['id' => $id]);
    return $st->fetchAll();
}

// --------------------------------------------------------------------------
// Pickers
// --------------------------------------------------------------------------
/** Buildings for an office, offices for a desk. Empty for a building (it has no parent). */
function parent_options(PDO $pdo, string $kind): array
{
    $parentKind = match ($kind) {
        'office' => 'building',
        'desk' => 'office',
        default => null,
    };
    if ($parentKind === null) {
        return [];
    }
    $st = $pdo->prepare("SELECT location_id, name FROM mcp_locations WHERE kind = :k AND status = 'active'
                          ORDER BY name");
    $st->execute(['k' => $parentKind]);
    return $st->fetchAll();
}

/** Desk owners are humans only (the schema's CHECK on locations_desk_has_owner is kind-based,
 *  not role-based — this is the form's own narrowing, per the spec). */
function find_human_member_options(PDO $pdo): array
{
    return $pdo->query("SELECT member_id, display_name FROM mcp_team_directory
                          WHERE member_kind = 'human' ORDER BY display_name")->fetchAll();
}

/**
 * The office-manager picker: agent_profiles(member_id). Empty until Agent HR ships — the
 * screen says why rather than showing a broken or empty-looking control silently.
 */
function find_agent_profile_options(PDO $pdo): array
{
    return $pdo->query("
        SELECT ap.member_id, td.display_name
          FROM agent_profiles ap
          JOIN mcp_team_directory td ON td.member_id = ap.member_id
         WHERE ap.status = 'active'
         ORDER BY td.display_name
    ")->fetchAll();
}

/** The reader's name for a stored platform key. */
function location_platform_label(?string $key): string
{
    if ($key === null || $key === '') {
        return '—';
    }
    return LOCATION_PLATFORM_LABELS[$key] ?? $key;
}

/** Yes / No / not recorded — NULL is a real state here and must not read as "no". */
function yes_no_unrecorded(?bool $v): string
{
    if ($v === null) {
        return 'Not recorded';
    }
    return $v ? 'Yes' : 'No';
}
