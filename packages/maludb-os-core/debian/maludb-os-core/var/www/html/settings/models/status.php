<?php
declare(strict_types=1);

/** Action `model_set_status` — log `model.set_status`. Gate: super. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/models.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('model');
$status = request_string('status');
if ($id === null || ($before = find_model($pdo, $id)) === null) {
    http_response_code(404);
    exit('Model not found.');
}
if (!in_array($status, MODEL_STATUSES, true)) {
    http_response_code(400);
    exit('That is not a status this app knows.');
}

check_approval($pdo, 'model_set_status', 'model.set_status', 'Set ' . $before['display_name'] . ' to ' . $status,
    ['model' => $id, 'status' => $status]);

$after = set_model_status($pdo, $id, $status);
if ($after === []) {
    http_response_code(500);
    exit('The model could not be updated.');
}

log_activity($pdo, 'model.set_status', 'model', $id, [
    'before' => ['status' => $before['status']], 'after' => ['status' => $after['status']],
]);
emit_action_status(true, ['did' => 'Set ' . $after['display_name'] . ' to ' . $status, 'refresh' => 'modelChanged']);
hx_trigger('modelChanged');

header('HX-Retarget: #page-content');
header('HX-Reswap: innerHTML');
header('HX-Push-Url: /settings/models');
echo view('settings/models.php', ['models' => find_models($pdo, true), 'errors' => []]);
