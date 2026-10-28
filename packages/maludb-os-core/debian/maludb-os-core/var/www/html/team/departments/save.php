<?php
declare(strict_types=1);

/** Action `department_save` — log `department.save`. Gate: admin (super-admin to create). */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';

require_business_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('department');

$fields = [
    'name' => request_string('name'),
    'description' => request_string('description') ?: null,
    'parent_id' => request_integer('parent_id'),
    'manager_member_id' => request_integer('manager_member_id'),
    'home_location_id' => request_integer('home_location_id'),
    'monthly_budget_amount' => request_string('monthly_budget_amount') !== '' ? request_string('monthly_budget_amount') : null,
    'budget_currency' => strtoupper(request_string('budget_currency', 'USD')) ?: 'USD',
    // The department's handbook, in the agents' context on every run (db/133: it lives here, not in Documents).
    'handbook_markdown' => request_string('handbook_markdown') !== '' ? request_string('handbook_markdown') : null,
];

$errors = [];
if ($fields['name'] === '' || mb_strlen($fields['name']) > 120) {
    $errors[] = 'A department needs a name (up to 120 characters).';
}
if ($fields['monthly_budget_amount'] !== null && !is_numeric($fields['monthly_budget_amount'])) {
    $errors[] = 'The budget must be a number, or blank.';
}
if ($fields['handbook_markdown'] !== null && strlen($fields['handbook_markdown']) > 60000) {
    $errors[] = 'The handbook is longer than 60,000 characters; agents read the first 12,000.';
}
if (strlen($fields['budget_currency']) !== 3) {
    $errors[] = 'Currency is a three-letter code.';
}
// The org chart is rooted at the Front Office (db/074), so a loop would detach a whole
// branch from it: refuse both the obvious case and the one a level or two down.
if ($id !== null && $fields['parent_id'] !== null) {
    if ($fields['parent_id'] === $id) {
        $errors[] = 'A department cannot be its own parent.';
    } elseif (department_would_cycle($pdo, $id, $fields['parent_id'])) {
        $errors[] = 'That department already reports to this one, directly or further down.';
    }
}

$before = null;
if ($id !== null) {
    $before = find_department($pdo, $id);
    if ($before === null) {
        http_response_code(404);
        exit('Department not found.');
    }
    require_admin_for_department($pdo, $id);
} elseif (!is_super_admin()) {
    deny('Only the super-admin creates departments.');
}

$renderForm = function (array $errs) use ($pdo, $id, $before, $fields): never {
    emit_action_status(false, ['errors' => $errs]);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    echo view('team/department-form.php', [
        'department' => array_merge($before ?? [], $fields, $id !== null ? ['department_id' => $id] : []),
        'members' => selectable_members($pdo),
        'locations' => business_locations($pdo),
        'departments' => find_departments($pdo),
        'errors' => $errs,
    ]);
    exit;
};

if ($errors !== []) {
    $renderForm($errors);
}

check_approval($pdo, 'department_save', 'department.save',
    ($id === null ? 'Create department ' : 'Update department ') . $fields['name'],
    array_merge($fields, ['department' => $id]), 'department', $id);

try {
    $department = upsert_department($pdo, $id, $fields);
} catch (PDOException $ex) {
    $msg = $ex->getCode() === '23505' ? 'A department with that name already exists.'
                                      : 'The department could not be saved.';
    if ($ex->getCode() !== '23505') {
        error_log('department save failed: ' . $ex->getMessage());
    }
    $renderForm([$msg]);
}

log_activity($pdo, 'department.save', 'department', (int) $department['id'], [
    'before' => $before,
    'after' => ['name' => $department['name'], 'manager_member_id' => $department['manager_member_id'],
                'home_location_id' => $department['home_location_id']],
]);
emit_action_status(true, ['did' => 'Saved department ' . $department['name']]);
hx_trigger('departmentChanged');

header('HX-Retarget: #page-content');
header('HX-Reswap: innerHTML');
header('HX-Push-Url: /team/departments/' . (int) $department['id']);   // the saved department, not the list (click-around R5)
echo view('team/departments.php', ['departments' => find_departments($pdo)]);
