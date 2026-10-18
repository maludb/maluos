<?php
declare(strict_types=1);

/** Application detail (screen `application-view`). Gate: insider — reading is open to anyone who works here; changing it needs mod:applications. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';

require_insider();
applications_require_files();

$pdo = db();
$id = request_integer('id');
if ($id === null || ($application = find_application($pdo, $id)) === null) {
    http_response_code(404);
    exit('Application not found.');
}
$tab = request_string('tab', 'overview') ?: 'overview';
$tab = in_array($tab, APPLICATION_VIEW_TABS, true) ? $tab : 'overview';

log_screen_view($pdo, 'application-view');
if (wants_json()) {
    require_once dirname(__DIR__, 2) . '/app/features/applications/present.php';
    require_once dirname(__DIR__, 2) . '/app/features/records/present.php';
    $viewerId = (int) current_member_id();
    $canManageAccess = can_manage_access($pdo);
    $grantRoles = application_grant_roles($pdo, $id);
    // Every tab's data travels at once: the tabs are one screen, and the four reads are cheap.
    respond_screen([
        'application' => present_application($application),
        'tab' => $tab,
        'gaps' => array_values(application_gaps($pdo, $id)),
        'endpoints' => array_map('present_application_endpoint', find_application_endpoints($pdo, $id)),
        'access' => array_map(static fn (array $a): array => present_application_access(
                $a + ['roles' => $grantRoles[(int) $a['application_access_id']] ?? []], $viewerId),
            find_application_access($pdo, $id)),
        // db/145: grants holding a role the application no longer publishes — to be changed.
        'withdrawn_holdings' => array_map(static fn (array $w): array => ['grant_id' => (int) $w['application_access_id'],
            'grantee' => (string) $w['grantee'], 'role_key' => (string) $w['role_key'], 'role_name' => (string) $w['role_name'],
            // Click-around step 2: the grantee as a link.
            'grantee_member_id' => isset($w['member_id']) ? (int) $w['member_id'] : null,
            'grantee_member_kind' => ($w['member_kind'] ?? '') !== '' ? (string) $w['member_kind'] : null,
            'grantee_department_id' => isset($w['department_id']) ? (int) $w['department_id'] : null,
            'grantee_location_id' => isset($w['resident_location_id']) ? (int) $w['resident_location_id'] : null],
            grants_holding_withdrawn_roles($pdo, $id)),
        'roles_synced_at' => json_ts(application_roles_synced_at($pdo, $id)),
        'retirement_counts' => array_map('intval', application_retirement_counts($pdo, $id)),
        // Expertise belongs to an application that runs (db/130).
        'expertise' => [
            'available' => in_array($application['status'], APPLICATION_RUNNING_STATUSES, true) && !empty($application['module_enabled']),
            'skills' => array_map('present_application_skill', find_application_skills($pdo, $id)),
            'agents' => can_edit_applications($pdo) ? array_map(static fn (array $o): array
                => ['id' => (int) $o['member_id'], 'name' => (string) $o['display_name']], application_expert_options($pdo)) : [],
            'can_set_skills' => can_set_application_skills($pdo),
            // A runbook (or skill) of the application can be given to one agent from here (owner, 2026-09-27).
            'agent_options' => can_set_application_skills($pdo) ? (static function () use ($pdo): array {
                require_once dirname(__DIR__, 2) . '/app/features/skills/queries.php';
                return skill_assign_options($pdo)['agents'];
            })() : [],
        ],
        // What one installation serves and the application's own roles (db/141).
        'roles' => array_map('present_application_role', find_application_roles($pdo, $id)),
        'scopes' => array_map('present_application_scope', find_application_scopes($pdo, $id)),
        'options' => $canManageAccess ? [
            'members' => array_map('present_member_option', selectable_members($pdo)),
            'departments' => array_map('present_department_option', find_departments($pdo)),
            'capabilities' => ACCESS_CAPABILITIES,
            // Sites and offices people reside at: the "everyone at" grantee, and a location scope's picker.
            'sites' => array_map(static fn (array $l): array => ['id' => (int) $l['location_id'], 'name' => (string) $l['name'],
                'kind' => (string) $l['kind']], application_residence_options($pdo)),
        ] : ['members' => [], 'departments' => [], 'capabilities' => ACCESS_CAPABILITIES, 'sites' => []],
        'kernel_token' => present_application_token(application_token($pdo, $id)),
        'can' => ['edit' => can_edit_applications($pdo), 'manage_access' => $canManageAccess,
                  'mint_token' => is_super_admin() && empty($application['is_builtin']),
                  'set_roles' => is_super_admin() && empty($application['is_builtin']),
                  // Read the roles from the application itself (db/145): one that has an MCP endpoint.
                  'refresh_roles' => is_super_admin() && empty($application['is_builtin'])
                      && array_filter(find_application_endpoints($pdo, $id), static fn (array $e): bool
                          => ($e['kind'] ?? '') === 'mcp' && ($e['status'] ?? '') === 'active') !== []],
    ]);
}
render_screen(($application['name'] ?? 'Application') . ' · ' . business_name($pdo),
    view('applications/application.php', [
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
        'errors' => [],
    ]),
    ['activeNav' => 'nav-applications', 'screen' => 'application-view', 'entity' => 'application', 'recordId' => (string) $id]);
