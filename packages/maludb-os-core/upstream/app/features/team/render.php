<?php
declare(strict_types=1);

/**
 * Shared re-render for the member access editor. The write endpoints (role, grants,
 * department membership) all answer with the refreshed editor in #page-content, which is the
 * exemplar's "write success -> refreshed screen" pattern applied to a settings-style screen.
 */
function render_member_access_page(PDO $pdo, int $memberId, array $errors = []): never
{
    require_once __DIR__ . '/queries.php';
    $member = find_team_member($pdo, $memberId);
    if ($member === null) {
        http_response_code(404);
        exit('Member not found.');
    }
    if ($errors !== []) {
        emit_action_status(false, ['errors' => $errors]);
    }
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    header('HX-Push-Url: /team/' . $memberId . '/edit');
    echo view('team/form.php', [
        'member' => $member,
        'departments' => member_departments($pdo, $memberId),
        'allDepartments' => find_departments($pdo),
        'grants' => member_module_grants($pdo, $memberId),
        'modules' => grantable_modules(),
        'isSuper' => is_super_admin(),
        'errors' => $errors,
    ]);
    exit;
}
