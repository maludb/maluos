<?php
declare(strict_types=1);

/** Model registry (screen `models-settings`). Gate: super. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/models.php';

require_super_admin();

$pdo = db();
log_screen_view($pdo, 'models-settings');
if (wants_json()) {
    require_once dirname(__DIR__, 3) . '/app/features/settings/present.php';
    respond_screen([
        'models' => array_map('present_model', find_models($pdo, true)),
        'statuses' => MODEL_STATUSES,
    ]);
}
render_screen('Models · ' . business_name($pdo),
    view('settings/models.php', ['models' => find_models($pdo, true), 'errors' => []]),
    ['activeNav' => 'nav-settings', 'screen' => 'models-settings']);
