<?php
declare(strict_types=1);

/**
 * Action `system_prompt_version_create` — log `system_prompt_version.create`. Gate: mod:hr.
 * Always a new version, never an edit — system_prompt_versions_no_edit refuses an UPDATE to
 * body or parameters at the database level; this endpoint only ever inserts.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/prompts.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/queries.php';

require_module_grant('hr');
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('system_prompt');
if ($id === null || ($prompt = find_system_prompt($pdo, $id)) === null) {
    http_response_code(404);
    exit('Prompt not found.');
}

[$fields, $errors] = system_prompt_version_fields_from_request();

$renderForm = function (array $errs) use ($pdo, $id, $prompt, $fields): never {
    emit_action_status(false, ['errors' => $errs]);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    echo view('settings/prompt.php', [
        'prompt' => $prompt,
        'versions' => find_system_prompt_versions($pdo, $id),
        'usedByCount' => count_configs_citing_prompt($pdo, $id),
        'isHr' => has_module($pdo, 'hr'),
        'newVersionFields' => $fields,
        'errors' => $errs,
    ]);
    exit;
};

if ($errors !== []) {
    $renderForm($errors);
}

check_approval($pdo, 'system_prompt_version_create', 'system_prompt_version.create',
    'New version for ' . $prompt['name'], $fields, 'system_prompt', $id);

try {
    $prompt = create_system_prompt_version($pdo, $id, $fields, (int) current_member_id());
} catch (PDOException $ex) {
    error_log('system prompt version create failed: ' . $ex->getMessage());
    $renderForm(['The version could not be saved.']);
}
if ($prompt === []) {
    $renderForm(['The version could not be saved.']);
}

log_activity($pdo, 'system_prompt_version.create', 'system_prompt', $id, [
    'after' => ['version_no' => $prompt['current_version'], 'change_note' => $fields['change_note']],
]);
emit_action_status(true, [
    'did' => 'Created version ' . $prompt['current_version'] . ' of ' . $prompt['name'],
    'refresh' => 'systemPromptChanged',
]);
hx_trigger('systemPromptChanged');

header('HX-Retarget: #page-content');
header('HX-Reswap: innerHTML');
header('HX-Push-Url: /settings/prompts/' . $id);
echo view('settings/prompt.php', [
    'prompt' => $prompt,
    'versions' => find_system_prompt_versions($pdo, $id),
    'usedByCount' => count_configs_citing_prompt($pdo, $id),
    'isHr' => has_module($pdo, 'hr'),
    'errors' => [],
]);
