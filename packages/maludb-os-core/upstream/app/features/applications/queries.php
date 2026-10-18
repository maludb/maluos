<?php
declare(strict_types=1);

/**
 * Applications: the technical asset registry (build spec: docs/build-specs/applications.md).
 *
 * db/075 made this registry the single source of truth for every MCP server an agent can use:
 * agent_tool_grants.application_endpoint_id points at application_endpoints, and an endpoint
 * marked agent_reachable with kind='mcp' and status='active' is immediately offerable in the
 * Agent HR tool-grant picker (app/features/agents/queries.php's find_grantable_tool_endpoints(),
 * which reads mcp_application_endpoints — the same view this file reads). That is why every
 * change here is logged and why removing an endpoint must name what depends on it.
 *
 * Reads come from the mcp_* views; writes go to base tables, as the Contacts exemplar and every
 * later slice established. Two things this file must NOT do, because the database already
 * guarantees them:
 *   - re-check application_access_one_grantee (member XOR department) — the CHECK constraint
 *     does that; a violation surfaces as a PDOException the endpoint turns into a field error;
 *   - re-check that a tool grant still points at an endpoint before deleting it — the FK's
 *     ON DELETE RESTRICT protects against a hard delete, which is exactly why endpoint removal
 *     here is a status change (see remove_application_endpoint()'s docblock), not a delete.
 *
 * No secret value is ever read, held, rendered or logged by anything in this file: secret_id
 * stays NULL (the Stripe slice builds the secret store), and mcp_application_endpoints exposes
 * only has_credential, a boolean.
 */

const APPLICATION_PAGE_SIZE = 25;
const APPLICATION_SORT_ALLOWED = ['name', 'category', 'criticality', 'health_status'];
const APPLICATION_CATEGORIES = ['platform', 'accounting', 'crm', 'calendar', 'email', 'documents',
    'storage', 'database', 'communication', 'automation', 'development', 'security', 'inventory', 'manufacturing',
    'investor_relations', 'other'];
const ENDPOINT_KINDS = ['mcp', 'http_api', 'database', 'filesystem', 'smtp', 'imap', 'ssh', 'ui', 'webhook'];
const ENDPOINT_AUTH_KINDS = ['none', 'bearer', 'oauth', 'basic', 'api_key', 'os_credential', 'mtls'];
const ACCESS_CAPABILITIES = ['read', 'write', 'admin'];
const APPLICATION_SCOPE_KINDS = ['none', 'location', 'department'];
const APPLICATION_CRITICALITIES = ['low', 'normal', 'high', 'critical'];
const APPLICATION_STATUSES = ['planned', 'active', 'degraded', 'retired'];
const APPLICATION_VIEW_TABS = ['overview', 'endpoints', 'access', 'scopes', 'expertise'];
const APPLICATION_RUNNING_STATUSES = ['active', 'degraded'];

// --------------------------------------------------------------------------
// Lists
// --------------------------------------------------------------------------
function find_applications(PDO $pdo, array $filters, string $sort = 'name', int $page = 1): array
{
    $sort = in_array($sort, APPLICATION_SORT_ALLOWED, true) ? $sort : 'name';
    $orderBy = match ($sort) {
        'category' => 'a.category ASC, a.name ASC',
        'criticality' => "array_position(ARRAY['critical','high','normal','low'], a.criticality) ASC, a.name ASC",
        'health_status' => "array_position(ARRAY['down','degraded','unknown','up'], a.health_status) ASC, a.name ASC",
        default => 'a.name ASC',
    };
    [$where, $params] = application_filter_sql($filters);
    $offset = (max(1, $page) - 1) * APPLICATION_PAGE_SIZE;

    $st = $pdo->prepare("
        SELECT a.*, count(*) OVER() AS total_count,
               coalesce(ep.endpoint_count, 0) AS endpoint_count,
               coalesce(ep.has_agent_mcp, false) AS has_agent_mcp
          FROM mcp_applications a
          LEFT JOIN LATERAL (
              SELECT count(*) AS endpoint_count,
                     bool_or(e.kind = 'mcp' AND e.agent_reachable) AS has_agent_mcp
                FROM mcp_application_endpoints e
               WHERE e.application_id = a.application_id
          ) ep ON true
          {$where}
         ORDER BY {$orderBy}
         LIMIT :lim OFFSET :off
    ");
    foreach ($params as $key => $value) {
        $st->bindValue($key, $value);
    }
    $st->bindValue('lim', APPLICATION_PAGE_SIZE, PDO::PARAM_INT);
    $st->bindValue('off', $offset, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}

/** @return array{0: string, 1: array} the WHERE clause and its bound values */
function application_filter_sql(array $filters): array
{
    $where = [];
    $params = [];

    if (($filters['category'] ?? '') !== '') {
        $where[] = 'a.category = :category';
        $params['category'] = $filters['category'];
    }
    if (($filters['owner_department_id'] ?? null) !== null) {
        $where[] = 'a.owner_department_id = :department';
        $params['department'] = (int) $filters['owner_department_id'];
    }
    if (($filters['location_id'] ?? null) !== null) {
        $where[] = 'a.location_id = :location';
        $params['location'] = (int) $filters['location_id'];
    }
    if (($filters['health'] ?? '') !== '') {
        $where[] = 'a.health_status = :health';
        $params['health'] = $filters['health'];
    }
    if (!empty($filters['gaps'])) {
        $where[] = application_gap_condition();
    }
    return [$where === [] ? '' : 'WHERE ' . implode(' AND ', $where), $params];
}

/**
 * AC4's own definition, one place: no owner department, or no health check in 30 days, or a
 * live endpoint whose auth_kind is not 'none' and has no credential attached. Reused by the
 * gaps=1 filter (find_applications) and by application_gaps() (the per-row reasons).
 */
function application_gap_condition(): string
{
    return "(a.owner_department_id IS NULL
             OR a.last_health_check_at IS NULL
             OR a.last_health_check_at < now() - interval '30 days'
             OR EXISTS (SELECT 1 FROM mcp_application_endpoints e
                         WHERE e.application_id = a.application_id
                           AND e.auth_kind <> 'none' AND e.has_credential = false)
             OR " . application_expert_gap_condition() . ")";
}

/** The expert is named but may not use the application: naming one never grants access (db/130). */
function application_expert_gap_condition(): string
{
    return "(a.sme_agent_member_id IS NOT NULL AND a.status IN ('active', 'degraded')
             AND NOT (a.application_id = ANY (app_member_application_ids(a.sme_agent_member_id))))";
}

// --------------------------------------------------------------------------
// The inventory (screen `applications-list`, db/130)
// --------------------------------------------------------------------------
/**
 * Every registered application, for the cards. Filters: business_area_id, owner_department_id,
 * health, gaps, retired (false hides retired rows). No paging — the inventory is one page.
 */
function find_application_inventory(PDO $pdo, array $filters): array
{
    [$where, $params] = application_filter_sql($filters);
    $conditions = $where === '' ? [] : [substr($where, 6)];
    if (($filters['business_area_id'] ?? null) !== null) {
        $conditions[] = 'a.business_area_id = :area';
        $params['area'] = (int) $filters['business_area_id'];
    }
    if (empty($filters['retired'])) {
        $conditions[] = "a.status <> 'retired'";
    }
    $whereSql = $conditions === [] ? '' : 'WHERE ' . implode(' AND ', $conditions);

    $st = $pdo->prepare("
        SELECT a.*, c.icon AS catalog_icon, c.sort_order AS catalog_sort,
               coalesce(ep.endpoint_count, 0) AS endpoint_count,
               coalesce(ep.has_agent_mcp, false) AS has_agent_mcp,
               (SELECT count(*) FROM mcp_skill_assignments s WHERE s.application_id = a.application_id) AS skill_count
          FROM mcp_applications a
          LEFT JOIN mcp_application_catalog c ON c.catalog_key = a.catalog_key
          LEFT JOIN LATERAL (
              SELECT count(*) AS endpoint_count,
                     bool_or(e.kind = 'mcp' AND e.agent_reachable) AS has_agent_mcp
                FROM mcp_application_endpoints e
               WHERE e.application_id = a.application_id
          ) ep ON true
          {$whereSql}
         ORDER BY coalesce(c.sort_order, 5000), a.name
    ");
    $st->execute($params);
    return $st->fetchAll();
}

/** Catalog entries nothing registered carries: what the business could run and does not. */
function find_available_catalog_entries(PDO $pdo, ?int $businessAreaId = null): array
{
    $st = $pdo->prepare("
        SELECT c.*
          FROM mcp_application_catalog c
         WHERE NOT EXISTS (SELECT 1 FROM mcp_applications a
                            WHERE a.catalog_key = c.catalog_key AND a.status <> 'retired')
           AND (CAST(:area AS bigint) IS NULL OR c.business_area_id = :area)
         ORDER BY c.sort_order, c.name
    ");
    $st->execute(['area' => $businessAreaId]);
    return $st->fetchAll();
}

function find_catalog_entry(PDO $pdo, string $catalogKey): ?array
{
    $st = $pdo->prepare('SELECT * FROM mcp_application_catalog WHERE catalog_key = :k');
    $st->execute(['k' => $catalogKey]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** Business areas in menu order — nav_groups; the unheaded group is what people open every day. */
function find_business_areas(PDO $pdo): array
{
    return $pdo->query('SELECT id AS business_area_id, name, sort_order FROM nav_groups ORDER BY sort_order, id')->fetchAll();
}

// --------------------------------------------------------------------------
// Single records
// --------------------------------------------------------------------------
function find_application(PDO $pdo, int $id): ?array
{
    // The location join is purely informational (the siting badge on Overview) — the estate
    // module still owns location CRUD; this is read-only, like estate's own
    // find_location_applications() reading mcp_applications the other way round.
    // (Control was dropped from the product by db/095, so it is no longer selected here.)
    $st = $pdo->prepare('
        SELECT a.*, l.siting
          FROM mcp_applications a
          LEFT JOIN mcp_locations l ON l.location_id = a.location_id
         WHERE a.application_id = :id
    ');
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** The AC4 reasons for one row, spelled out rather than a bare "has a gap" flag. */
function application_gaps(PDO $pdo, int $id): array
{
    $reasons = [];
    $st = $pdo->prepare('SELECT a.owner_department_id, a.last_health_check_at, a.sme_agent_name,
                                ' . application_expert_gap_condition() . ' AS expert_gap
                           FROM mcp_applications a
                          WHERE a.application_id = :id');
    $st->execute(['id' => $id]);
    $app = $st->fetch();
    if ($app === false) {
        return [];
    }
    if ($app['owner_department_id'] === null) {
        $reasons[] = 'no owner department';
    }
    if ($app['last_health_check_at'] === null) {
        $reasons[] = 'never health-checked';
    } elseif (strtotime((string) $app['last_health_check_at']) < strtotime('-30 days')) {
        $reasons[] = 'no health check in the last 30 days';
    }
    $st = $pdo->prepare("SELECT name FROM mcp_application_endpoints
                          WHERE application_id = :id AND auth_kind <> 'none' AND has_credential = false
                          ORDER BY name");
    $st->execute(['id' => $id]);
    foreach ($st->fetchAll(PDO::FETCH_COLUMN) as $name) {
        $reasons[] = 'endpoint "' . $name . '" needs a credential';
    }
    if (!empty($app['expert_gap'])) {
        $reasons[] = 'expert ' . $app['sme_agent_name'] . ' has no access to this application';
    }
    return $reasons;
}

// --------------------------------------------------------------------------
// Writes: applications
// --------------------------------------------------------------------------
function upsert_application(PDO $pdo, ?int $id, array $f): array
{
    if ($id === null) {
        $st = $pdo->prepare(<<<'SQL'
            INSERT INTO applications
                (name, app_key, category, description, vendor, is_self_hosted, location_id,
                 owner_department_id, owner_member_id, url, version, criticality,
                 notes, created_by, catalog_key, business_area_id, sso_path, sso_logout_path, directory_writes,
                 scope_kind)
            VALUES
                (:name, :app_key, :category, :description, :vendor, :self_hosted, :location,
                 :dept, :owner, :url, :version, :criticality, :notes, :created_by, :catalog_key,
                 CASE WHEN CAST(:area_sent AS boolean) THEN CAST(:area AS bigint) END, :sso_path, :sso_logout_path, :directory_writes,
                 CASE WHEN CAST(:scope_kind_sent AS boolean) THEN CAST(:scope_kind AS text) ELSE 'none' END)
            RETURNING id
        SQL);
        $params = application_params($f);
        $params['app_key'] = $f['app_key'];
        $params['created_by'] = $f['created_by'] ?? null;
        $params['catalog_key'] = $f['catalog_key'] ?? null;
    } else {
        // app_key is read-only on edit — it is an identifier other things (endpoints, access,
        // agent tool grants through the endpoint) point at.
        $st = $pdo->prepare(<<<'SQL'
            UPDATE applications
               SET name = :name, category = :category, description = :description,
                   vendor = :vendor, is_self_hosted = :self_hosted, location_id = :location,
                   owner_department_id = :dept, owner_member_id = :owner, url = :url,
                   version = :version, criticality = :criticality,
                   notes = :notes, sso_path = :sso_path, sso_logout_path = :sso_logout_path,
                   directory_writes = :directory_writes,
                   business_area_id = CASE WHEN CAST(:area_sent AS boolean) THEN CAST(:area AS bigint)
                                           ELSE business_area_id END,
                   scope_kind = CASE WHEN CAST(:scope_kind_sent AS boolean) THEN CAST(:scope_kind AS text)
                                     ELSE scope_kind END,
                   updated_at = now()
             WHERE id = :id
            RETURNING id
        SQL);
        $params = application_params($f);
        $params['id'] = $id;
    }
    $st->execute($params);
    $row = $st->fetch();
    return $row === false ? [] : (find_application($pdo, (int) $row['id']) ?? []);
}

function application_params(array $f): array
{
    return [
        'name' => $f['name'],
        'category' => $f['category'],
        'description' => $f['description'] ?? null,
        'vendor' => $f['vendor'] ?? null,
        'self_hosted' => !empty($f['is_self_hosted']) ? 't' : 'f',
        'location' => $f['location_id'] ?? null,
        'dept' => $f['owner_department_id'] ?? null,
        'owner' => $f['owner_member_id'] ?? null,
        'url' => $f['url'] ?? null,
        'version' => $f['version'] ?? null,
        'criticality' => $f['criticality'] ?? 'normal',
        'notes' => $f['notes'] ?? null,
        'sso_path' => $f['sso_path'] ?? null,
        'sso_logout_path' => $f['sso_logout_path'] ?? null,
        'directory_writes' => !empty($f['directory_writes']) ? 't' : 'f',
        'area_sent' => !empty($f['business_area_sent']) ? 't' : 'f',
        'area' => $f['business_area_id'] ?? null,
        'scope_kind_sent' => !empty($f['scope_kind_sent']) ? 't' : 'f',
        'scope_kind' => $f['scope_kind'] ?? 'none',
    ];
}

/**
 * Retiring is a status, not a delete — the manifest's own words. Nothing cascades: live access
 * grants and endpoints are left exactly as they are; application_retirement_counts() is what
 * lets the confirm dialog say how many of each there are before the click.
 */
function set_application_status(PDO $pdo, int $id, string $status): array
{
    $st = $pdo->prepare("
        UPDATE applications
           SET status = :status,
               retired_at = CASE WHEN :status2 = 'retired' THEN now() ELSE retired_at END,
               -- only a running application has an expert (db/130): retiring lets the agent go
               sme_agent_member_id = CASE WHEN :status3 = 'retired' THEN NULL ELSE sme_agent_member_id END,
               updated_at = now()
         WHERE id = :id
        RETURNING id
    ");
    $st->execute(['status' => $status, 'status2' => $status, 'status3' => $status, 'id' => $id]);
    $row = $st->fetch();
    return $row === false ? [] : (find_application($pdo, $id) ?? []);
}

/** What a retire confirmation should say before the click, per the manifest. */
function application_retirement_counts(PDO $pdo, int $id): array
{
    $st = $pdo->prepare("
        SELECT
            (SELECT count(*) FROM application_access WHERE application_id = :id1 AND revoked_at IS NULL) AS access_grants,
            (SELECT count(*) FROM application_endpoints WHERE application_id = :id2 AND status = 'active') AS endpoints
    ");
    $st->execute(['id1' => $id, 'id2' => $id]);
    $row = $st->fetch();
    return $row === false ? ['access_grants' => 0, 'endpoints' => 0] : $row;
}

// --------------------------------------------------------------------------
// Endpoints
// --------------------------------------------------------------------------
function find_application_endpoints(PDO $pdo, int $applicationId): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_application_endpoints WHERE application_id = :id ORDER BY name');
    $st->execute(['id' => $applicationId]);
    return $st->fetchAll();
}

function find_application_endpoint(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT * FROM mcp_application_endpoints WHERE application_endpoint_id = :id');
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

function upsert_application_endpoint(PDO $pdo, ?int $id, array $f): array
{
    if ($id === null) {
        $st = $pdo->prepare(<<<'SQL'
            INSERT INTO application_endpoints
                (application_id, name, kind, url, auth_kind, agent_reachable, mcp_surface_version, notes)
            VALUES (:app, :name, :kind, :url, :auth, :reachable, :surface, :notes)
            RETURNING id
        SQL);
        $params = endpoint_params($f);
        $params['app'] = $f['application_id'];
    } else {
        $st = $pdo->prepare(<<<'SQL'
            UPDATE application_endpoints
               SET name = :name, kind = :kind, url = :url, auth_kind = :auth,
                   agent_reachable = :reachable, mcp_surface_version = :surface,
                   notes = :notes, updated_at = now()
             WHERE id = :id
            RETURNING id
        SQL);
        $params = endpoint_params($f);
        $params['id'] = $id;
    }
    $st->execute($params);
    $row = $st->fetch();
    return $row === false ? [] : (find_application_endpoint($pdo, (int) $row['id']) ?? []);
}

function endpoint_params(array $f): array
{
    return [
        'name' => $f['name'],
        'kind' => $f['kind'],
        'url' => $f['url'] ?? null,
        'auth' => $f['auth_kind'] ?? 'none',
        'reachable' => !empty($f['agent_reachable']) ? 't' : 'f',
        'surface' => $f['mcp_surface_version'] ?? null,
        'notes' => $f['notes'] ?? null,
    ];
}

/**
 * "Remove" is a status change (active -> retired), not a hard DELETE — a deliberate substitution
 * from the spec's literal "the FK is ON DELETE RESTRICT, catch the PDOException" wording.
 * agent_tool_grants.application_endpoint_id -> application_endpoints(id) ON DELETE RESTRICT
 * blocks a DELETE for as long as ANY row (revoked or not) still references the endpoint —
 * agent_tool_grants never deletes a row on revoke, only stamps revoked_at (the audit trail is
 * kept on purpose). A literal hard delete would therefore stay refused forever, even after the
 * one live grant blocking it is revoked, which would break the exact acceptance step ("revoke
 * the grant, then the removal succeeds") this behaviour exists to satisfy.
 *
 * So the caller (html/applications/endpoints/remove.php) checks endpoint_dependents() itself —
 * the retire_location() pattern (app/features/estate/queries.php): name who is in the way
 * BEFORE writing, rather than discovering it from a caught exception. Once nothing live points
 * at it, retiring the endpoint removes it from mcp_application_endpoints (filtered to
 * status = 'active') without ever touching agent_tool_grants — the same "a status, not a
 * delete" reasoning set_application_status() uses for the application itself.
 */
function remove_application_endpoint(PDO $pdo, int $id): bool
{
    $st = $pdo->prepare("UPDATE application_endpoints SET status = 'retired', updated_at = now()
                          WHERE id = :id AND status = 'active'");
    $st->execute(['id' => $id]);
    return $st->rowCount() > 0;
}

/** The agents to name in application_endpoint_remove's refusal — only LIVE grants. */
function endpoint_dependents(PDO $pdo, int $id): array
{
    $st = $pdo->prepare("
        SELECT DISTINCT m.display_name
          FROM agent_tool_grants g
          JOIN members m ON m.id = g.agent_member_id
         WHERE g.application_endpoint_id = :id AND g.revoked_at IS NULL
         ORDER BY m.display_name
    ");
    $st->execute(['id' => $id]);
    return $st->fetchAll(PDO::FETCH_COLUMN);
}

// --------------------------------------------------------------------------
// Access
// --------------------------------------------------------------------------
function find_application_access(PDO $pdo, int $applicationId): array
{
    // granted_by_name: the grantor's name for the Access tab (click-around step 2) — the view carries only the id.
    $st = $pdo->prepare('SELECT x.*, gb.display_name AS granted_by_name
                           FROM mcp_application_access x
                           LEFT JOIN members gb ON gb.id = x.granted_by
                          WHERE x.application_id = :id
                          ORDER BY x.granted_at DESC');
    $st->execute(['id' => $applicationId]);
    return $st->fetchAll();
}

/**
 * Grant access. On an application that publishes roles, `roles` is the set the grant gives (db/145):
 * the grant's role_key becomes the highest of them — its capability is the grant's — and every one is
 * recorded in application_access_roles. A single `role_key` still works (one role). The caller owns
 * the transaction when it needs one; the insert and its roles are one statement's worth of work.
 *
 * @throws PDOException the triggers' own sentences (a role that is not, or no longer, offered).
 */
function grant_application_access(PDO $pdo, int $applicationId, array $f, int $by): array
{
    $roles = array_values(array_unique(array_filter(array_map('strval', $f['roles'] ?? []), static fn (string $r): bool => $r !== '')));
    if ($roles === [] && ($f['role_key'] ?? null) !== null) {
        $roles = [(string) $f['role_key']];
    }
    if ($roles !== []) {
        $f['role_key'] = top_application_role($pdo, $applicationId, $roles) ?? $roles[0];
    }
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO application_access
            (application_id, member_id, department_id, resident_location_id, scope_id, role_key,
             capability, granted_by, expires_at, note)
        VALUES (:app, :member, :dept, :residents, :scope, :role, :capability, :by, :expires, :note)
        RETURNING id
    SQL);
    $st->execute([
        'app' => $applicationId,
        'member' => $f['member_id'] ?? null,
        'dept' => $f['department_id'] ?? null,
        'residents' => $f['resident_location_id'] ?? null,
        'scope' => $f['scope_id'] ?? null,
        'role' => $f['role_key'] ?? null,
        'capability' => $f['capability'] ?? 'read',
        'by' => $by,
        'expires' => $f['expires_at'] ?? null,
        'note' => $f['note'] ?? null,
    ]);
    $row = $st->fetch();
    if ($row === false) {
        return [];
    }
    $add = $pdo->prepare('INSERT INTO application_access_roles (application_access_id, application_id, role_key)
                          VALUES (:g, :app, :role)');
    foreach ($roles as $role) {
        $add->execute(['g' => $row['id'], 'app' => $applicationId, 'role' => $role]);
    }
    $st2 = $pdo->prepare('SELECT * FROM mcp_application_access WHERE application_access_id = :id');
    $st2->execute(['id' => $row['id']]);
    return $st2->fetch() ?: [];
}

/** Revoke one live grant — only one of this application's, so a grant id cannot reach across applications. */
function revoke_application_access(PDO $pdo, int $id, int $by, ?int $applicationId = null): bool
{
    $st = $pdo->prepare('UPDATE application_access SET revoked_at = now(), revoked_by = :by
                          WHERE id = :id AND revoked_at IS NULL
                            AND (CAST(:app AS bigint) IS NULL OR application_id = CAST(:app AS bigint))');
    $st->execute(['by' => $by, 'id' => $id, 'app' => $applicationId]);
    return $st->rowCount() > 0;
}

/**
 * Change what a live grant admits to — its role, or its capability on an application without
 * roles. The old grant is revoked and a new one made for the same grantee, scope, expiry and
 * note, so the grant's history stays dated (who held what, from when to when). The caller owns
 * the transaction. Returns [before, after] rows of mcp_application_access, or [] if the grant is
 * not live on this application.
 *
 * @throws PDOException the trigger's own sentence when the role is not the application's.
 */
/** The role that gives the most among $roles (capability, then the application's order); null if none is its. */
function top_application_role(PDO $pdo, int $applicationId, array $roles): ?string
{
    $st = $pdo->prepare('SELECT role_key FROM application_roles
                          WHERE application_id = :app AND role_key IN (SELECT jsonb_array_elements_text(CAST(:keys AS jsonb)))
                          ORDER BY app_capability_rank(capability) DESC, sort_order, id LIMIT 1');
    $st->execute(['app' => $applicationId, 'keys' => json_encode(array_values($roles))]);
    $key = $st->fetchColumn();
    return $key === false ? null : (string) $key;
}

/** "Payroll, Employee" — role keys as the application names them, for a person to read. */
function application_role_names(PDO $pdo, int $applicationId, array $keys): string
{
    $st = $pdo->prepare('SELECT role_key, name FROM application_roles WHERE application_id = :app');
    $st->execute(['app' => $applicationId]);
    $names = $st->fetchAll(PDO::FETCH_KEY_PAIR);
    return implode(', ', array_map(static fn (string $k): string => (string) ($names[$k] ?? $k), $keys));
}

/** The roles each live grant of an application gives (db/145), keyed by grant id. */
function application_grant_roles(PDO $pdo, int $applicationId): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_application_access_roles WHERE application_id = :app ORDER BY role_key');
    $st->execute(['app' => $applicationId]);
    $by = [];
    foreach ($st->fetchAll() as $r) {
        $by[(int) $r['application_access_id']][] = $r;
    }
    return $by;
}

function change_application_access(PDO $pdo, int $applicationId, int $grantId, ?string $roleKey, string $capability, int $by, array $roles = []): array
{
    $st = $pdo->prepare('SELECT * FROM application_access WHERE id = :id AND application_id = :app
                            AND revoked_at IS NULL FOR UPDATE');
    $st->execute(['id' => $grantId, 'app' => $applicationId]);
    $old = $st->fetch();
    if ($old === false) {
        return [];
    }
    $before = $pdo->prepare('SELECT * FROM mcp_application_access WHERE application_access_id = :id');
    $before->execute(['id' => $grantId]);
    $beforeRow = $before->fetch() ?: [];
    revoke_application_access($pdo, $grantId, $by, $applicationId);
    $after = grant_application_access($pdo, $applicationId, [
        'member_id' => $old['member_id'], 'department_id' => $old['department_id'],
        'resident_location_id' => $old['resident_location_id'], 'scope_id' => $old['scope_id'],
        'role_key' => $roleKey, 'roles' => $roles, 'capability' => $capability,
        'expires_at' => $old['expires_at'], 'note' => $old['note'],
    ], $by);
    return $after === [] ? [] : [$beforeRow, $after];
}

// --------------------------------------------------------------------------
// "What can I reach, and how?" (AC2)
// --------------------------------------------------------------------------
function find_my_applications(PDO $pdo): array
{
    return $pdo->query('SELECT * FROM mcp_my_applications ORDER BY name')->fetchAll();
}

// --------------------------------------------------------------------------
// Expertise: the expert agent and the application's skills (db/130)
// --------------------------------------------------------------------------
/** Agents that can be named expert: hired and not let go. */
function application_expert_options(PDO $pdo): array
{
    return $pdo->query("SELECT p.member_id, m.display_name
                          FROM agent_profiles p JOIN members m ON m.id = p.member_id
                         WHERE p.status = 'active' ORDER BY m.display_name")->fetchAll();
}

/** Null clears the expert. Naming one grants nothing — access stays a module or access grant. */
function set_application_expert(PDO $pdo, int $id, ?int $agentMemberId): bool
{
    $st = $pdo->prepare('UPDATE applications SET sme_agent_member_id = :agent WHERE id = :id');
    $st->execute(['agent' => $agentMemberId, 'id' => $id]);
    return $st->rowCount() === 1;
}

function find_application_skills(PDO $pdo, int $applicationId): array
{
    $st = $pdo->prepare("SELECT s.*, coalesce(k.kind, 'skill') AS kind FROM mcp_skill_assignments s LEFT JOIN skill_kinds k ON k.skill_name = s.skill_name
                          WHERE s.application_id = :a ORDER BY (coalesce(k.kind, 'skill') = 'runbook') DESC, s.skill_name");
    $st->execute(['a' => $applicationId]);
    return $st->fetchAll();
}


/**
 * What the launcher offers this person (A2): the applications mcp_my_applications admits them to —
 * a live grant of their own or their department's, or all of them for a super-admin — that are not
 * the platform's own row and not a built-in module. Ordered as the Applications inventory is.
 */
function find_listed_applications(PDO $pdo): array
{
    // db/155: one view of the launcher's own, gated by app_can_launch() — an external with a live grant is admitted.
    return $pdo->query("
        SELECT l.application_id, l.name, l.app_key, l.category, l.url, l.status, l.capability, l.sso_path,
               l.description, l.business_area_name, l.business_area_sort, l.icon, a.scope_kind
          FROM mcp_launcher_applications l
          JOIN applications a ON a.id = l.application_id
         ORDER BY l.business_area_sort NULLS LAST, l.name
         LIMIT 200")->fetchAll();
}

/**
 * The applications the signed-in person can actually open (the owner, 2026-09-28: the launcher shows nothing
 * that does not launch): active, at a real address (a reserved test name — .invalid, .test, .example,
 * .localhost — never answers), and, split by site or department and entered through the hand-off, held at one
 * scope at least. The launcher, /home and the default-application choice all read this one list.
 */
function find_launchable_applications(PDO $pdo): array
{
    $held = find_my_application_scopes($pdo);
    return array_values(array_filter(find_listed_applications($pdo), static function (array $a) use ($held): bool {
        if (!application_is_openable($a)) {
            return false;
        }
        $host = strtolower((string) parse_url(trim((string) $a['url']), PHP_URL_HOST));
        if ($host === '' || $host === 'localhost' || preg_match('/\.(invalid|test|example|localhost)$/', $host) === 1) {
            return false;
        }
        return ($a['scope_kind'] ?? 'none') === 'none' || ($a['sso_path'] ?? '') === ''
            || ($held[(int) $a['application_id']] ?? []) !== [];
    }));
}

/** The launcher's scope links (db/141): every scope the signed-in person holds, by application id. */
function find_my_application_scopes(PDO $pdo): array
{
    $by = [];
    foreach ($pdo->query('SELECT * FROM mcp_my_application_scopes ORDER BY application_id, scope_name')->fetchAll() as $r) {
        $by[(int) $r['application_id']][] = $r;
    }
    return $by;
}

// ---- the application token (A4, db/136) ---------------------------------------------------------
/** The application's live token, if any: when it was minted and last used — never the value. */
function application_token(PDO $pdo, int $applicationId): ?array
{
    $st = $pdo->prepare("SELECT id, member_id, created_at, last_used_at FROM mcp_access_tokens
                          WHERE application_id = :a AND scope = 'application' AND revoked_at IS NULL");
    $st->execute(['a' => $applicationId]);
    return $st->fetch() ?: null;
}

/** Mint (or rotate): any live token is revoked first — one per application. @return array{raw:string,id:int} */
function mint_application_token(PDO $pdo, int $applicationId, int $minterMemberId, string $label): array
{
    $raw = 'osapp_' . bin2hex(random_bytes(24));
    $pdo->beginTransaction();
    try {
        revoke_application_tokens($pdo, $applicationId);
        $st = $pdo->prepare("INSERT INTO mcp_access_tokens (member_id, label, token_hash, scope, application_id)
                              VALUES (:m, :l, :h, 'application', :a) RETURNING id");
        $st->execute(['m' => $minterMemberId, 'l' => $label, 'h' => hash('sha256', $raw), 'a' => $applicationId]);
        $id = (int) $st->fetchColumn();
        $pdo->commit();
    } catch (Throwable $e) {
        $pdo->rollBack();
        throw $e;
    }
    return ['raw' => $raw, 'id' => $id];
}

function revoke_application_tokens(PDO $pdo, int $applicationId): int
{
    $st = $pdo->prepare("UPDATE mcp_access_tokens SET revoked_at = now()
                          WHERE application_id = :a AND scope = 'application' AND revoked_at IS NULL");
    $st->execute(['a' => $applicationId]);
    return $st->rowCount();
}

// --------------------------------------------------------------------------
// Roles and scopes (db/141 — docs/build-specs/kernel-scoped-applications.md)
// --------------------------------------------------------------------------
function find_application_roles(PDO $pdo, int $applicationId): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_application_roles WHERE application_id = :id ORDER BY sort_order, application_role_id');
    $st->execute(['id' => $applicationId]);
    return $st->fetchAll();
}

function find_application_scopes(PDO $pdo, int $applicationId): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_application_scopes WHERE application_id = :id ORDER BY scope_name, scope_id');
    $st->execute(['id' => $applicationId]);
    return $st->fetchAll();
}

function find_application_scope(PDO $pdo, int $scopeId): ?array
{
    $st = $pdo->prepare('SELECT * FROM mcp_application_scopes WHERE scope_id = :id');
    $st->execute(['id' => $scopeId]);
    return $st->fetch() ?: null;
}

/**
 * Replace an application's declared roles with $roles (each: key, name, capability, is_admin), in
 * the order given. A role held by a live grant cannot be dropped — the trigger's sentence says so and
 * the whole replacement rolls back. The caller owns the transaction.
 */
function set_application_roles(PDO $pdo, int $applicationId, array $roles): void
{
    $keys = array_map(static fn (array $r): string => $r['key'], $roles);
    $drop = $pdo->prepare('DELETE FROM application_roles WHERE application_id = :app AND NOT (role_key = ANY (CAST(:keys AS text[])))');
    $drop->execute(['app' => $applicationId, 'keys' => '{' . implode(',', $keys) . '}']);
    // One admin role at a time: clear the flag before the upsert sets it where it now belongs.
    $pdo->prepare('UPDATE application_roles SET is_admin = false WHERE application_id = :app AND is_admin')
        ->execute(['app' => $applicationId]);
    $up = $pdo->prepare(<<<'SQL'
        INSERT INTO application_roles (application_id, role_key, name, capability, is_admin, sort_order)
        VALUES (:app, :key, :name, :capability, :is_admin, :sort)
        ON CONFLICT (application_id, role_key)
        DO UPDATE SET name = EXCLUDED.name, capability = EXCLUDED.capability,
                      is_admin = EXCLUDED.is_admin, sort_order = EXCLUDED.sort_order
    SQL);
    foreach (array_values($roles) as $i => $r) {
        $up->execute(['app' => $applicationId, 'key' => $r['key'], 'name' => $r['name'],
                      'capability' => $r['capability'], 'is_admin' => $r['is_admin'] ? 't' : 'f', 'sort' => $i + 1]);
    }
}

function add_application_scope(PDO $pdo, int $applicationId, ?int $locationId, ?int $departmentId, int $by): array
{
    $st = $pdo->prepare('INSERT INTO application_scopes (application_id, location_id, department_id, added_by)
                         VALUES (:app, :loc, :dept, :by) RETURNING id');
    $st->execute(['app' => $applicationId, 'loc' => $locationId, 'dept' => $departmentId, 'by' => $by]);
    $id = $st->fetchColumn();
    return $id === false ? [] : (find_application_scope($pdo, (int) $id) ?? []);
}

/** Remove a scope; its live grants are revoked by trigger in the same statement. Returns how many. */
function remove_application_scope(PDO $pdo, int $scopeId, int $by): ?int
{
    $count = $pdo->prepare('SELECT count(*) FROM application_access WHERE scope_id = :id AND revoked_at IS NULL');
    $count->execute(['id' => $scopeId]);
    $revoked = (int) $count->fetchColumn();
    $st = $pdo->prepare('UPDATE application_scopes SET removed_at = now(), removed_by = :by
                          WHERE id = :id AND removed_at IS NULL');
    $st->execute(['id' => $scopeId, 'by' => $by]);
    return $st->rowCount() > 0 ? $revoked : null;
}

/** Live sites and offices, for the "everyone at" grantee and a location scope's picker. */
function application_residence_options(PDO $pdo): array
{
    return $pdo->query("SELECT location_id, name, kind FROM mcp_locations
                         WHERE kind IN ('site', 'office') AND status = 'active' ORDER BY kind DESC, name")->fetchAll();
}

// ---- the landing page on app.<domain> (db/142 — docs/build-specs/kernel-default-application.md) -------

/** An application a launcher card can open: active, with an address. */
function application_is_openable(array $a): bool
{
    return ($a['status'] ?? '') === 'active' && preg_match('#^https?://#i', trim((string) ($a['url'] ?? ''))) === 1;
}

/** Where opening this card goes: through the hand-off when it takes the platform's sign-on, else its address. */
function application_open_path(array $a, ?int $scopeId = null): string
{
    if (($a['sso_path'] ?? '') !== '') {
        return '/launch/' . (int) $a['application_id'] . ($scopeId !== null ? '?scope=' . $scopeId : '');
    }
    return trim((string) $a['url']);
}

/**
 * Where app.<domain>/ takes the signed-in person — the launcher's own list decides, so the two can
 * never disagree. A super-admin: the launcher (it carries the operating system). Otherwise: the
 * default application while it is still theirs and openable (with its scope when they still hold
 * it); else, holding exactly one application, that one; else the launcher — saying so when they hold
 * nothing, or when the default could not be opened.
 *   ['kind' => 'open', 'path' => '/launch/5?scope=2'|'https://…', 'application_id' => 5]
 *   ['kind' => 'launcher', 'notice' => null|string]
 */
function app_home_destination(PDO $pdo, array $member, string $askedAppKey = ''): array
{
    // An application sent the person here (?app=<its key>: they reached it with no session there) — take them
    // straight back when they hold it and it opens; a site-scoped one they hold at several sites, or at none,
    // stays on the launcher with a word why. Anyone, a super-admin included.
    if ($askedAppKey !== '') {
        foreach (find_listed_applications($pdo) as $a) {
            if ((string) $a['app_key'] !== $askedAppKey || !application_is_openable($a)) {
                continue;
            }
            $st = $pdo->prepare('SELECT scope_kind FROM applications WHERE id = :id');
            $st->execute(['id' => (int) $a['application_id']]);
            $scoped = ($st->fetchColumn() ?: 'none') !== 'none';
            $held = array_map(static fn (array $s): int => (int) $s['scope_id'], find_my_application_scopes($pdo)[(int) $a['application_id']] ?? []);
            if ($scoped && $held === []) {
                return ['kind' => 'launcher', 'notice' => $a['name'] . ' has no ' . 'site or department you can open yet'
                    . (($member['business_role'] ?? '') === 'super_admin' ? ' — add them on its Scopes tab.' : '.')];
            }
            if ($scoped && count($held) > 1 && ($a['sso_path'] ?? '') !== '') {
                return ['kind' => 'launcher', 'notice' => 'Choose where to open ' . $a['name'] . '.'];
            }
            return ['kind' => 'open', 'application_id' => (int) $a['application_id'],
                    'path' => application_open_path($a, count($held) === 1 ? $held[0] : null)];
        }
        return ['kind' => 'launcher', 'notice' => 'That application could not be opened — choose one below.'];
    }
    if (($member['business_role'] ?? '') === 'super_admin') {
        return ['kind' => 'launcher', 'notice' => null];
    }
    $apps = find_launchable_applications($pdo);
    $byId = [];
    foreach ($apps as $a) {
        $byId[(int) $a['application_id']] = $a;
    }
    $notice = null;
    $defaultId = isset($member['default_application_id']) ? (int) $member['default_application_id'] : null;
    if ($defaultId !== null) {
        $a = $byId[$defaultId] ?? null;
        if ($a !== null && application_is_openable($a)) {
            $scope = isset($member['default_scope_id']) ? (int) $member['default_scope_id'] : null;
            $held = array_map(static fn (array $s): int => (int) $s['scope_id'], find_my_application_scopes($pdo)[$defaultId] ?? []);
            return ['kind' => 'open', 'application_id' => $defaultId,
                    'path' => application_open_path($a, $scope !== null && in_array($scope, $held, true) ? $scope : null)];
        }
        $notice = 'Your default application could not be opened — choose one below.';
    }
    if (count($apps) === 1 && application_is_openable($apps[0])) {
        return ['kind' => 'open', 'application_id' => (int) $apps[0]['application_id'], 'path' => application_open_path($apps[0])];
    }
    return ['kind' => 'launcher', 'notice' => $notice];
}

/**
 * The applications a member holds, as the choices for their default: each with the scopes they hold
 * there. For any member (their own settings, or an administrator on their page) — the grants decide,
 * through all three routes (app_member_grants), or being a super-admin.
 */
function member_default_application_options(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT a.id AS application_id, a.name, a.scope_kind
          FROM applications a
         WHERE NOT a.is_builtin AND a.app_key IS DISTINCT FROM 'platform' AND a.status <> 'retired'
           AND (EXISTS (SELECT 1 FROM app_member_grants(a.id, :m))
                OR EXISTS (SELECT 1 FROM members m WHERE m.id = :m AND m.status = 'active' AND m.business_role = 'super_admin'))
         ORDER BY a.name
    SQL);
    $st->execute(['m' => $memberId]);
    $out = [];
    foreach ($st->fetchAll() as $a) {
        $scopes = [];
        if ($a['scope_kind'] !== 'none') {
            $sc = $pdo->prepare('SELECT scope_id, scope_name FROM app_member_application_scopes(:a, :m)');
            $sc->execute(['a' => $a['application_id'], 'm' => $memberId]);
            $scopes = array_map(static fn (array $s): array => ['id' => (int) $s['scope_id'], 'name' => (string) $s['scope_name']], $sc->fetchAll());
        }
        $out[] = ['id' => (int) $a['application_id'], 'name' => (string) $a['name'], 'scopes' => $scopes];
    }
    return $out;
}

/** The member's default as the settings and member screens show it, with the choices. */
function present_member_default_application(PDO $pdo, array $member): array
{
    return [
        'application_id' => isset($member['default_application_id']) ? (int) $member['default_application_id'] : null,
        'scope_id' => isset($member['default_scope_id']) ? (int) $member['default_scope_id'] : null,
        'options' => member_default_application_options($pdo, (int) $member['id']),
    ];
}
