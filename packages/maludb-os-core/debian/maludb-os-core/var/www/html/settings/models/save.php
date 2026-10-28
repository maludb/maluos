<?php
declare(strict_types=1);

/** Action `model_save` — log `model.save`. Gate: super. No API keys in this slice —
 *  api_secret_id stays NULL until the Stripe slice builds the tenant secret store. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/render.php';
agents_require_files();

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('model');
[$fields, $errors] = model_fields_from_request();

$renderForm = function (array $errs) use ($id, $fields): never {
    emit_action_status(false, ['errors' => $errs]);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    echo view('settings/model-form.php', [
        'model' => array_merge($fields, $id !== null ? ['model_id' => $id] : []),
        'isEdit' => $id !== null, 'errors' => $errs,
    ]);
    exit;
};

if ($errors !== []) {
    $renderForm($errors);
}

if ($id !== null && ($current = find_model($pdo, $id)) !== null
    && ($current['auth_mode'] ?? 'api_key') !== $fields['auth_mode'] && model_in_use($pdo, $id)) {
    $renderForm(['Agents already use this model, so how it bills cannot change. Register a separate model row for the other way of billing (a Max-plan model is its own row).']);
}

check_approval($pdo, 'model_save', 'model.save', ($id === null ? 'Register model ' : 'Update model ') . $fields['display_name'], $fields);

try {
    $model = upsert_model($pdo, $id, $fields);
} catch (PDOException $ex) {
    error_log('model save failed: ' . $ex->getMessage());
    if ($ex->getCode() === '23505') {
        $renderForm(['A model with that key already exists.']);
    }
    $renderForm(['The model could not be saved.']);
}
if ($model === []) {
    $renderForm(['The model could not be saved.']);
}

log_activity($pdo, 'model.save', 'model', (int) $model['model_id'], [
    'after' => ['model_key' => $model['model_key'], 'display_name' => $model['display_name'], 'status' => $model['status'],
               'auth_mode' => $model['auth_mode'] ?? 'api_key'],
]);
emit_action_status(true, ['did' => 'Saved ' . $model['display_name'], 'refresh' => 'modelChanged']);
hx_trigger('modelChanged');

header('HX-Retarget: #page-content');
header('HX-Reswap: innerHTML');
header('HX-Push-Url: /settings/models/' . (int) $model['model_id'] . '/edit');   // the saved model (owner, 2026-09-27: land on the record)
echo view('settings/models.php', ['models' => find_models($pdo, true), 'errors' => []]);
