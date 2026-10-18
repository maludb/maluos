<?php
declare(strict_types=1);

/**
 * Action `system_prompt_save` — log `system_prompt.save`. Gate: mod:hr. With no `prompt`,
 * creates a new prompt AND its version 1 in one transaction (a prompt with no text cannot
 * exist) — this is what `/settings/prompts/new` posts. With `prompt` set, updates only the
 * metadata (prompt_key, name, description, role_key); a version's body/parameters can never be
 * edited here (system_prompt_versions_no_edit) — see version-save.php.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/prompts.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/queries.php';

require_module_grant('hr');
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('prompt');
$existing = $id !== null ? find_system_prompt($pdo, $id) : null;
if ($id !== null && $existing === null) {
    http_response_code(404);
    exit('Prompt not found.');
}

[$fields, $errors] = system_prompt_fields_from_request();
if ($id === null && $fields['body'] === '') {
    $errors[] = 'A new prompt needs its first version — the text the model receives.';
}

$renderForm = function (array $errs) use ($id, $fields): never {
    emit_action_status(false, ['errors' => $errs]);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    echo view('settings/prompt-form.php', [
        'prompt' => array_merge($fields, $id !== null ? ['system_prompt_id' => $id] : []),
        'errors' => $errs,
    ]);
    exit;
};

if ($errors !== []) {
    $renderForm($errors);
}

check_approval($pdo, 'system_prompt_save', 'system_prompt.save',
    ($id === null ? 'Create prompt ' : 'Update prompt ') . $fields['name'], $fields,
    $id !== null ? 'system_prompt' : null, $id);

try {
    $prompt = $id === null
        ? create_system_prompt($pdo, $fields, (int) current_member_id())
        : update_system_prompt_meta($pdo, $id, $fields);
} catch (PDOException $ex) {
    error_log('system prompt save failed: ' . $ex->getMessage());
    if ($ex->getCode() === '23505') {
        $renderForm(['A prompt with that key already exists.']);
    }
    $renderForm(['The prompt could not be saved.']);
}
if ($prompt === []) {
    $renderForm(['The prompt could not be saved.']);
}

log_activity($pdo, 'system_prompt.save', 'system_prompt', (int) $prompt['system_prompt_id'], [
    'after' => ['prompt_key' => $prompt['prompt_key'], 'name' => $prompt['name']],
]);
emit_action_status(true, ['did' => 'Saved ' . $prompt['name'], 'refresh' => 'systemPromptChanged']);
hx_trigger('systemPromptChanged');

header('HX-Retarget: #page-content');
header('HX-Reswap: innerHTML');
header('HX-Push-Url: /settings/prompts/' . (int) $prompt['system_prompt_id']);
echo view('settings/prompt.php', [
    'prompt' => $prompt,
    'versions' => find_system_prompt_versions($pdo, (int) $prompt['system_prompt_id']),
    'usedByCount' => count_configs_citing_prompt($pdo, (int) $prompt['system_prompt_id']),
    'isHr' => has_module($pdo, 'hr'),
    'errors' => [],
]);
