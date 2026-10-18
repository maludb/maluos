<?php
declare(strict_types=1);

/** Member access editor (screen `member-edit`). Gate: admin over that person. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/team/queries.php';

require_business_admin();

$pdo = db();
$id = request_integer('id');
if ($id === null || ($member = find_team_member($pdo, $id)) === null) {
    http_response_code(404);
    exit('Member not found.');
}
if (!can_admin_member($pdo, $id)) {
    deny('You do not administer this person.');
}

log_screen_view($pdo, 'member-edit');
if (wants_json()) {
    require_once dirname(__DIR__, 2) . '/app/features/team/present.php';
    require_once dirname(__DIR__, 2) . '/app/features/records/present.php';
    respond_screen([
        'member' => present_team_member($member, current_member()['timezone'] ?? 'UTC'),
        'departments' => array_map('present_member_department', member_departments($pdo, $id)),
        'modules' => present_module_access(grantable_modules(), member_module_grants($pdo, $id)),
        // What they can use beyond the OS: application grants — their own (editable here) and inherited.
        'application_grants' => array_map('present_member_application_grant', member_application_grants($pdo, $id)),
        'application_options' => array_map('present_grantable_application', grantable_applications($pdo)),
        'options' => ['departments' => array_map('present_department_option', find_departments($pdo))],
        'can' => ['set_role' => is_super_admin(),
                  // The application access handlers' own gate: the super-admin (2026-09-27).
                  'manage_applications' => is_super_admin(),
                  // OS module grants only matter where the member can reach the OS screens: an agent
                  // (on its run token), or anyone when the tenant runs one face (no OS_HOST).
                  'kernel_modules' => ($member['member_kind'] ?? '') === 'agent' || os_host() === '',
                  // A person's details are maintained here too (member_update, 2026-09-26); agents in Agent HR.
                  'update' => ($member['member_kind'] ?? '') === 'human'],
        'timezones' => timezone_identifiers_list(),
    ]);
}
$pageHtml = view('team/form.php', [
    'member' => $member,
    'departments' => member_departments($pdo, $id),
    'allDepartments' => find_departments($pdo),
    'grants' => member_module_grants($pdo, $id),
    'modules' => grantable_modules(),
    'isSuper' => is_super_admin(),
    'errors' => $errors ?? [],
]);
render_screen('Access · ' . $member['display_name'] . ' · ' . business_name($pdo), $pageHtml,
    ['activeNav' => 'nav-agents', 'screen' => 'member-edit', 'entity' => 'member', 'recordId' => (string) $id]);
