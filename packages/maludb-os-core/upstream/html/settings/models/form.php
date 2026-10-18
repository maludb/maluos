<?php
declare(strict_types=1);

/** Model add/edit form (screens `model-add` / `model-edit`). Gate: super. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/render.php';

require_super_admin();
agents_require_files();

$pdo = db();
$id = request_integer('id');
$model = [];
if ($id !== null) {
    $model = find_model($pdo, $id);
    if ($model === null) {
        http_response_code(404);
        exit('Model not found.');
    }
    // The view hides endpoint_url; the form must still show it or a save erases it (decision 10).
    $model['endpoint_url'] = find_model_endpoint_url($pdo, $id);
}

log_screen_view($pdo, $id === null ? 'model-add' : 'model-edit');
if (wants_json()) {
    require_once dirname(__DIR__, 3) . '/app/features/settings/present.php';
    require_once dirname(__DIR__, 3) . '/app/features/agents/runs.php';
    respond_screen([
        // endpoint_url travels with the FORM payload only — never with present_model(), which the
        // registry list shares.
        'model' => present_model($model) + ['endpoint_url' => $model['endpoint_url'] ?? null],
        // Registering a model ahead of its harness is legitimate, so the form says which
        // harnesses exist rather than hiding the rest; the HIRE is what refuses (runs.php).
        'options' => ['providers' => MODEL_PROVIDERS, 'harnesses' => MODEL_HARNESSES, 'statuses' => MODEL_STATUSES,
                      'built_harnesses' => built_harnesses(), 'auth_modes' => MODEL_AUTH_MODES,
                      // Whether the runner has the Max-plan switch on (null = the runner could not be asked).
                      'subscription' => (static function (): ?bool { $h = runner_request('GET', '/health'); return $h['status'] === 200 ? !empty($h['body']['subscription']) : null; })()],
    ]);
}
render_screen(($id === null ? 'Register a model' : 'Edit model') . ' · ' . business_name($pdo),
    view('settings/model-form.php', ['model' => $model, 'isEdit' => $id !== null, 'errors' => []]),
    ['activeNav' => 'nav-settings', 'screen' => $id === null ? 'model-add' : 'model-edit']);
