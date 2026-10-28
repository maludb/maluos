<?php
declare(strict_types=1);

/**
 * Shared re-renders and field parsers for the applications screens — the exemplar's "a write
 * answers with the whole refreshed screen" pattern, so no endpoint assembles a view of its own.
 * Every render_*_page() here emits status: error through the action channel whenever it is
 * called with a non-empty $errors array — the fix the Expenses and Books slices both had to
 * make: a validation error re-rendered with HTTP 200 reads as success to the assistant and to
 * every agent unless X-Action-Status says otherwise.
 */

function applications_require_files(): void
{
    require_once __DIR__ . '/queries.php';
    require_once __DIR__ . '/health.php';
    require_once __DIR__ . '/roles.php';
    require_once dirname(__DIR__) . '/team/queries.php';
}

// --------------------------------------------------------------------------
// Capability flags (mirror the gate exactly — never has_module() alone, which admits any
// business admin and would over-show write controls the endpoint itself would then refuse)
// --------------------------------------------------------------------------
/** mod:applications (no comma): super-admin or a grant holder. Matches require_module_grant(). */
function can_edit_applications(PDO $pdo): bool
{
    if (is_super_admin()) {
        return true;
    }
    $st = $pdo->prepare('SELECT app_has_module(:m)');
    $st->execute(['m' => 'applications']);
    return (bool) $st->fetchColumn();
}

/** Who grants, changes and revokes application access: the super-admin only (2026-09-27 — the
 *  roles a grant gives are rights inside the application). Matches the access handlers' gate. */
function can_manage_access(PDO $pdo): bool
{
    return is_super_admin();
}

/**
 * The roles a grant gives (db/145): `roles[]` from a form or the actions MCP (a repeated field), or a
 * comma-separated `roles`, or the single `role` of before. Keys only, de-duplicated, in order.
 */
function access_roles_from_request(): array
{
    $raw = $_POST['roles'] ?? [];
    $list = is_array($raw) ? $raw : explode(',', (string) $raw);
    $role = request_string('role');
    if ($role !== '') {
        $list[] = $role;
    }
    $out = [];
    foreach ($list as $r) {
        $r = strtolower(trim((string) $r));
        if ($r !== '' && !in_array($r, $out, true)) {
            $out[] = $r;
        }
    }
    return $out;
}

/** Who may say which skills an application carries: can_assign_skill()'s application rule (HR, or mod:applications). Never an agent. */
function can_set_application_skills(PDO $pdo): bool
{
    require_once dirname(__DIR__) . '/skills/queries.php';
    return can_assign_skill($pdo, 'application', null, null);
}

// --------------------------------------------------------------------------
// Pickers
// --------------------------------------------------------------------------
/** Offices and desks only — a building does not run applications directly. */
function application_location_options(PDO $pdo): array
{
    return $pdo->query("SELECT location_id, name, kind FROM mcp_locations
                          WHERE kind IN ('office', 'desk') AND status = 'active'
                          ORDER BY kind, name")->fetchAll();
}

/** The accountable person: humans only. */
function application_owner_options(PDO $pdo): array
{
    return $pdo->query("SELECT member_id, display_name FROM mcp_team_directory
                          WHERE member_kind = 'human' ORDER BY display_name")->fetchAll();
}

// --------------------------------------------------------------------------
// List
// --------------------------------------------------------------------------
function application_list_filters(): array
{
    return [
        'category' => request_string('category'),
        'owner_department_id' => request_integer('department'),
        'location_id' => request_integer('location'),
        'health' => request_string('health'),
        'gaps' => request_bool('gaps'),
    ];
}

function render_applications_list(PDO $pdo, array $errors = []): never
{
    applications_require_files();
    if ($errors !== []) {
        emit_action_status(false, ['errors' => $errors]);
    }
    $filters = application_list_filters();
    $page = request_integer('page') ?? 1;
    $rows = find_applications($pdo, $filters, request_string('sort', 'name'), $page);
    $total = (int) ($rows[0]['total_count'] ?? 0);
    $gapsByApp = [];
    if (!empty($filters['gaps'])) {
        foreach ($rows as $r) {
            $gapsByApp[(int) $r['application_id']] = application_gaps($pdo, (int) $r['application_id']);
        }
    }
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    header('HX-Push-Url: /applications/');
    echo view('applications/applications.php', [
        'applications' => $rows,
        'filters' => $filters,
        'page' => $page,
        'totalPages' => max(1, (int) ceil($total / APPLICATION_PAGE_SIZE)),
        'gapsByApp' => $gapsByApp,
        'departments' => find_departments($pdo),
        'locations' => application_location_options($pdo),
        'errors' => $errors,
    ]);
    exit;
}

// --------------------------------------------------------------------------
// Application detail (tabbed: overview / endpoints / access / expertise)
// --------------------------------------------------------------------------
function render_application_page(PDO $pdo, int $id, string $tab = 'overview', array $errors = []): never
{
    applications_require_files();
    if ($errors !== []) {
        emit_action_status(false, ['errors' => $errors]);
    }
    $application = find_application($pdo, $id);
    if ($application === null) {
        render_applications_list($pdo);
    }
    $tab = in_array($tab, APPLICATION_VIEW_TABS, true) ? $tab : 'overview';

    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    header('HX-Push-Url: /applications/' . $id . ($tab !== 'overview' ? '?tab=' . $tab : ''));
    echo view('applications/application.php', [
        'application' => $application,
        'tab' => $tab,
        'gaps' => application_gaps($pdo, $id),
        'endpoints' => find_application_endpoints($pdo, $id),
        'access' => find_application_access($pdo, $id),
        'retirementCounts' => application_retirement_counts($pdo, $id),
        'memberOptions' => selectable_members($pdo),
        'departmentOptions' => find_departments($pdo),
        'canEdit' => can_edit_applications($pdo),
        'canManageAccess' => can_manage_access($pdo),
        'myId' => (int) current_member_id(),
        'errors' => $errors,
    ]);
    exit;
}

// --------------------------------------------------------------------------
// The dedicated access screen (`application-access`)
// --------------------------------------------------------------------------
function render_application_access_page(PDO $pdo, int $id, array $errors = []): never
{
    applications_require_files();
    if ($errors !== []) {
        emit_action_status(false, ['errors' => $errors]);
    }
    $application = find_application($pdo, $id);
    if ($application === null) {
        render_applications_list($pdo);
    }
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    header('HX-Push-Url: /applications/access?application=' . $id);
    echo view('applications/access.php', [
        'application' => $application,
        'access' => find_application_access($pdo, $id),
        'memberOptions' => selectable_members($pdo),
        'departmentOptions' => find_departments($pdo),
        'canManageAccess' => can_manage_access($pdo),
        'myId' => (int) current_member_id(),
        'errors' => $errors,
    ]);
    exit;
}

// --------------------------------------------------------------------------
// Field parsing
// --------------------------------------------------------------------------
function application_fields_from_request(bool $isEdit): array
{
    $fields = [
        'name' => request_string('name'),
        'category' => request_string('category'),
        'description' => request_string('description') ?: null,
        'vendor' => request_string('vendor') ?: null,
        'is_self_hosted' => request_bool('is_self_hosted'),
        // The form sends *_id; the application_save tool (the manifest's words) sends location,
        // owner_department, owner_member — both are read, so neither door drops the value.
        'location_id' => request_integer('location_id') ?? request_integer('location'),
        'owner_department_id' => request_integer('owner_department_id') ?? request_integer('owner_department'),
        'owner_member_id' => request_integer('owner_member_id') ?? request_integer('owner_member'),
        'url' => request_string('url') ?: null,
        'sso_path' => request_string('sso_path') ?: null,
        'sso_logout_path' => request_string('sso_logout_path') ?: null,
        'directory_writes' => request_bool('directory_writes'),
        'version' => request_string('version') ?: null,
        'criticality' => request_string('criticality', 'normal'),
        'notes' => request_string('notes') ?: null,
        // An `application_save` call that does not know the field leaves the area as it is.
        'business_area_sent' => array_key_exists('business_area_id', $_POST),
        'business_area_id' => request_integer('business_area_id'),
        // What one installation serves (db/141): one set of data, one per site, or one per department.
        // A call that does not send it leaves it as it is.
        'scope_kind_sent' => array_key_exists('scope_kind', $_POST),
        'scope_kind' => request_string('scope_kind', 'none'),
    ];
    if (!$isEdit) {
        $fields['app_key'] = strtolower(trim(request_string('app_key')));
        $fields['catalog_key'] = request_string('catalog_key') ?: null;
    }

    $errors = [];
    if ($fields['name'] === '' || mb_strlen($fields['name']) > 200) {
        $errors[] = 'An application needs a name (up to 200 characters).';
    }
    if (!$isEdit && (!preg_match('/^[a-z][a-z0-9_]*$/', $fields['app_key']))) {
        $errors[] = 'The key is lowercase letters, digits and underscores, starting with a letter.';
    }
    if (!in_array($fields['category'], APPLICATION_CATEGORIES, true)) {
        $errors[] = 'That is not a category this app knows.';
    }
    if (!in_array($fields['criticality'], APPLICATION_CRITICALITIES, true)) {
        $errors[] = 'Criticality is low, normal, high or critical.';
    }
    if ($fields['url'] !== null && mb_strlen($fields['url']) > 2000) {
        $errors[] = 'That URL is too long.';
    }
    foreach (['sso_path' => 'The sign-on path', 'sso_logout_path' => 'The sign-out path'] as $key => $label) {
        if ($fields[$key] !== null && (!str_starts_with($fields[$key], '/') || mb_strlen($fields[$key]) > 200 || preg_match('/\\s/', $fields[$key]))) {
            $errors[] = $label . ' is a path on the application, starting with /, without spaces (up to 200 characters).';
        }
    }
    if (!in_array($fields['scope_kind'], APPLICATION_SCOPE_KINDS, true)) {
        $errors[] = 'An application serves one set of data (none), one per site (location) or one per department (department).';
    }
    if ($fields['sso_path'] !== null && $fields['url'] === null) {
        $errors[] = 'A sign-on path needs the application\'s address (URL) beside it.';
    }
    return [$fields, $errors];
}

function endpoint_fields_from_request(): array
{
    $fields = [
        'name' => request_string('name'),
        'kind' => request_string('kind'),
        'url' => request_string('url') ?: null,
        'auth_kind' => request_string('auth_kind', 'none'),
        'agent_reachable' => request_bool('agent_reachable'),
        'mcp_surface_version' => request_string('mcp_surface_version') ?: null,
        'notes' => request_string('notes') ?: null,
    ];
    $errors = [];
    if ($fields['name'] === '' || mb_strlen($fields['name']) > 200) {
        $errors[] = 'An endpoint needs a name (up to 200 characters).';
    }
    if (!in_array($fields['kind'], ENDPOINT_KINDS, true)) {
        $errors[] = 'That is not a kind of endpoint this app knows.';
    }
    if (!in_array($fields['auth_kind'], ENDPOINT_AUTH_KINDS, true)) {
        $errors[] = 'That is not an auth kind this app knows.';
    }
    return [$fields, $errors];
}

/** Grantee is member XOR department (application_access_one_grantee) — this only pre-checks the
 *  shape; the CHECK constraint is still what decides, surfaced as a field error if PHP somehow
 *  disagrees with it. */
function access_grant_fields_from_request(): array
{
    $memberId = request_integer('member');
    $departmentId = request_integer('department');
    // Grantee "everyone at": the residents of a site or office (db/141).
    $residentsId = request_integer('residents');
    $fields = [
        'member_id' => $memberId,
        'department_id' => $departmentId,
        'resident_location_id' => $residentsId,
        'capability' => request_string('capability', 'read'),
        // On a scoped application the grant names the site or department it admits to; on one that
        // declares roles it names the role, and the capability is the role's (set by trigger).
        'scope_id' => request_integer('scope'),
        'role_key' => request_string('role') ?: null,
        'roles' => access_roles_from_request(),
        'expires_at' => request_string('expires_at') ?: null,
        'note' => request_string('note') ?: null,
    ];
    $errors = [];
    if (count(array_filter([$memberId, $departmentId, $residentsId], static fn ($v): bool => $v !== null)) !== 1) {
        $errors[] = 'Grant access to one member, one department, or everyone at one site — exactly one of them.';
    }
    if ($fields['roles'] === [] && !in_array($fields['capability'], ACCESS_CAPABILITIES, true)) {
        $errors[] = 'Capability is read, write or admin.';
    }
    foreach ($fields['roles'] as $r) {
        if (!preg_match('/^[a-z][a-z0-9_]{0,39}$/', $r)) {
            $errors[] = $r . ' is not one of this application\'s roles.';
        }
    }
    if (!in_array($fields['capability'], ACCESS_CAPABILITIES, true)) {
        $fields['capability'] = 'read';   // replaced by the role's capability
    }
    return [$fields, $errors];
}

/** Read a trigger/CHECK's own ERROR text out of a PDOException, the agent_trigger_message()
 *  pattern (app/features/agents/render.php) applied here so the database's own sentence reaches
 *  the field error instead of a generic message. */
function application_trigger_message(PDOException $ex, string $fallback): string
{
    // Only a message one of our own triggers RAISEd (SQLSTATE P0001) is written for a person.
    // Anything else is the database talking — a constraint name is not an explanation, and it
    // reached an agent verbatim in the 2026-09-19 action smoke.
    if ($ex->getCode() === '23505') {
        return 'They already hold a live grant on this application — revoke it first, or change that one.';
    }
    if ($ex->getCode() === 'P0001' && preg_match('/ERROR:\s*(.+?)(\n|$)/s', $ex->getMessage(), $m)) {
        return trim($m[1]);
    }
    return $fallback;
}
