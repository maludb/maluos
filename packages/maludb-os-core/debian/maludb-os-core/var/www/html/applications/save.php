<?php
declare(strict_types=1);

/** Action `application_save` — log `application.save`. Gate: mod:applications (require_module_grant). */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';
applications_require_files();

require_module_grant('applications');
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('application');
$before = null;
if ($id !== null) {
    $before = find_application($pdo, $id);
    if ($before === null) {
        http_response_code(404);
        exit('Application not found.');
    }
}
[$fields, $errors] = application_fields_from_request($id !== null);
if ($id === null) {
    $fields['created_by'] = (int) current_member_id();
}

$renderForm = function (array $errs) use ($pdo, $id, $fields, $before): never {
    emit_action_status(false, ['errors' => $errs]);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    echo view('applications/application-form.php', [
        'application' => array_merge($fields, $id !== null
            ? ['application_id' => $id, 'app_key' => $before['app_key'] ?? ''] : []),
        'locationOptions' => application_location_options($pdo),
        'departmentOptions' => find_departments($pdo),
        'ownerOptions' => application_owner_options($pdo),
        'isEdit' => $id !== null,
        'errors' => $errs,
    ]);
    exit;
};

// An application is registered against a catalog entry of an outside product OR of an application
// from us (`ours`, db/139) — never against one of the kernel's own.
if (($fields['catalog_key'] ?? null) !== null
    && !in_array(find_catalog_entry($pdo, $fields['catalog_key'])['kind'] ?? '', ['external', 'ours'], true)) {
    $errors[] = 'That is not a product in the application catalog.';
}
if ($fields['business_area_id'] !== null
    && !in_array($fields['business_area_id'], array_map('intval', array_column(find_business_areas($pdo), 'business_area_id')), true)) {
    $errors[] = 'That is not a business area this business has.';
}
if ($errors !== []) {
    $renderForm($errors);
}

check_approval($pdo, 'application_save', 'application.save',
    ($id === null ? 'Register application: ' : 'Update application: ') . $fields['name'],
    $fields, 'application', $id);

try {
    $application = upsert_application($pdo, $id, $fields);
} catch (PDOException $ex) {
    error_log('application save failed: ' . $ex->getMessage());
    if ($ex->getCode() === '23505') {
        $renderForm(['An application with that name or key already exists.']);
    }
    $renderForm([application_trigger_message($ex, 'The application could not be saved.')]);
}
if ($application === []) {
    $renderForm(['The application could not be saved.']);
}

log_activity($pdo, 'application.save', 'application', (int) $application['application_id'], [
    'before' => $before,
    'after' => ['name' => $application['name'], 'category' => $application['category']],
]);
emit_action_status(true, ['did' => ($id === null ? 'Registered application ' : 'Updated application ') . $application['name'],
                          'refresh' => 'applicationChanged']);
hx_trigger('applicationChanged');
render_application_page($pdo, (int) $application['application_id'], 'overview');
