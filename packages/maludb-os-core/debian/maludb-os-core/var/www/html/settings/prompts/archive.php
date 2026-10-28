<?php
declare(strict_types=1);

/** Action `system_prompt_archive` — log `system_prompt.archive`. Gate: mod:hr. Refused while a
 *  live agent configuration cites it — archive_system_prompt() names them, the way
 *  retire_location() names what blocks a retirement. Restoring is never blocked. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/prompts.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/queries.php';

require_module_grant('hr');
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('system_prompt');
$archived = request_bool('archived');
if ($id === null || ($prompt = find_system_prompt($pdo, $id)) === null) {
    http_response_code(404);
    exit('Prompt not found.');
}

check_approval($pdo, 'system_prompt_archive', 'system_prompt.archive',
    ($archived ? 'Archive ' : 'Restore ') . $prompt['name'], ['system_prompt' => $id, 'archived' => $archived],
    'system_prompt', $id);

try {
    $after = archive_system_prompt($pdo, $id, $archived);
} catch (RuntimeException $ex) {
    emit_action_status(false, ['errors' => [$ex->getMessage()]]);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    echo view('settings/prompt.php', [
        'prompt' => $prompt,
        'versions' => find_system_prompt_versions($pdo, $id),
        'usedByCount' => count_configs_citing_prompt($pdo, $id),
        'isHr' => has_module($pdo, 'hr'),
        'errors' => [$ex->getMessage()],
    ]);
    exit;
}
if ($after === []) {
    http_response_code(500);
    exit('The prompt could not be updated.');
}

log_activity($pdo, 'system_prompt.archive', 'system_prompt', $id, [
    'after' => ['archived' => $archived, 'name' => $after['name']],
]);
emit_action_status(true, [
    'did' => ($archived ? 'Archived ' : 'Restored ') . $after['name'],
    'refresh' => 'systemPromptChanged',
]);
hx_trigger('systemPromptChanged');

header('HX-Retarget: #page-content');
header('HX-Reswap: innerHTML');
header('HX-Push-Url: /settings/prompts/' . $id);
echo view('settings/prompt.php', [
    'prompt' => $after,
    'versions' => find_system_prompt_versions($pdo, $id),
    'usedByCount' => count_configs_citing_prompt($pdo, $id),
    'isHr' => has_module($pdo, 'hr'),
    'errors' => [],
]);
