<?php
declare(strict_types=1);

/** Standalone access screen (screen `application-access`). Gate: insider — mcp_application_access narrows further in SQL. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';

require_insider();
applications_require_files();

$pdo = db();
$id = request_integer('application');
if ($id === null || ($application = find_application($pdo, $id)) === null) {
    http_response_code(404);
    exit('Application not found.');
}

log_screen_view($pdo, 'application-access');
render_screen('Access · ' . ($application['name'] ?? 'Application') . ' · ' . business_name($pdo),
    view('applications/access.php', [
        'application' => $application,
        'access' => find_application_access($pdo, $id),
        'memberOptions' => selectable_members($pdo),
        'departmentOptions' => find_departments($pdo),
        'canManageAccess' => can_manage_access($pdo),
        'myId' => (int) current_member_id(),
        'errors' => [],
    ]),
    ['activeNav' => 'nav-applications', 'screen' => 'application-access', 'entity' => 'application', 'recordId' => (string) $id]);
