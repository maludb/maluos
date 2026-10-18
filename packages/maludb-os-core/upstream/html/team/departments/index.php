<?php
declare(strict_types=1);

/** Departments list (screen `departments-list`). Gate: admin. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';

require_business_admin();

$pdo = db();
log_screen_view($pdo, 'departments-list');
if (wants_json()) {
    require_once dirname(__DIR__, 3) . '/app/features/team/present.php';
    respond_screen(['departments' => array_map('present_department', find_departments($pdo))]);
}
$pageHtml = view('team/departments.php', ['departments' => find_departments($pdo)]);
render_screen('Departments · ' . business_name($pdo), $pageHtml,
    ['activeNav' => 'nav-departments', 'screen' => 'departments-list']);
