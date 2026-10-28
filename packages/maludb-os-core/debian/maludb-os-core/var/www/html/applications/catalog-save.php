<?php
declare(strict_types=1);

/**
 * Action `application_catalog_save` — add or update a catalog entry an application is registered
 * against (A7 (f)): an application from us (`ours`) or anyone else's product (`external`). The
 * installation agent adds the `ours` row from maludb-os.json before it registers the application;
 * a person does the same here. Super-admin. The kernel's own entries (`builtin`) are seeds.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/render.php';
applications_require_files();
require_once dirname(__DIR__, 2) . '/app/features/applications/present.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$key = strtolower(trim(request_string('catalog_key')));
$fields = [
    'name' => trim(request_string('name')),
    'description' => trim(request_string('description')),
    'icon' => trim(request_string('icon')) ?: 'feather-grid',
    'kind' => request_string('kind', 'ours'),
    'vendor' => trim(request_string('vendor')) ?: null,
    'category' => request_string('category', 'other'),
    'business_area' => trim(request_string('business_area')),
];
$errors = [];
if (!preg_match('/^[a-z][a-z0-9_]{1,63}$/', $key)) {
    $errors[] = 'catalog_key is lowercase letters, digits and underscores, starting with a letter.';
}
if ($fields['name'] === '' || mb_strlen($fields['name']) > 200) {
    $errors[] = 'A catalog entry needs a name (up to 200 characters).';
}
if (!in_array($fields['kind'], ['ours', 'external'], true)) {
    $errors[] = 'kind is ours (an application from us) or external (anyone else\'s).';
}
if (!in_array($fields['category'], APPLICATION_CATEGORIES, true)) {
    $errors[] = 'That is not a category this app knows.';
}
$area = null;
foreach (find_business_areas($pdo) as $g) {
    if (strcasecmp((string) $g['name'], $fields['business_area']) === 0 || strcasecmp(business_area_label((string) $g['name']), $fields['business_area']) === 0) {
        $area = (int) $g['business_area_id'];
    }
}
if ($area === null) {
    $errors[] = 'business_area names one of the business areas (Everyday, Sales & Service, Finance, Operations, Human Resources, Administration, Technology & Infrastructure).';
}
$existing = find_catalog_entry($pdo, $key);
if ($existing !== null && $existing['kind'] === 'builtin') {
    $errors[] = 'That key is one of the kernel\'s own entries.';
}
if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);
}
$st = $pdo->prepare(<<<'SQL'
    INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category)
    VALUES (:k, :name, :descr, :icon, :area, :kind, :vendor, :category)
    ON CONFLICT (catalog_key) DO UPDATE
       SET name = EXCLUDED.name, description = EXCLUDED.description, icon = EXCLUDED.icon, business_area_id = EXCLUDED.business_area_id,
           kind = EXCLUDED.kind, vendor = EXCLUDED.vendor, category = EXCLUDED.category, updated_at = now()
SQL);
$st->execute(['k' => $key, 'name' => $fields['name'], 'descr' => $fields['description'], 'icon' => $fields['icon'],
    'area' => $area, 'kind' => $fields['kind'], 'vendor' => $fields['vendor'], 'category' => $fields['category']]);
log_activity($pdo, 'application_catalog.save', 'application_catalog', null, [
    'before' => $existing === null ? null : ['name' => $existing['name'], 'kind' => $existing['kind']],
    'after' => ['catalog_key' => $key] + $fields,
]);
emit_action_status(true, ['did' => ($existing === null ? 'Added ' : 'Updated ') . $fields['name'] . ' to the catalog as ' . $fields['kind'],
    'refresh' => 'applicationChanged', 'location' => '/applications']);
