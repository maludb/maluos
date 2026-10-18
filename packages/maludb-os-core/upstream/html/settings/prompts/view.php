<?php
declare(strict_types=1);

/** One prompt: its versions, who uses it, and the text of each (screen `system-prompt-view`).
 *  Gate: insider (writes — new version, archive, metadata edit — need mod:hr; the view itself
 *  gates each action's form the same way html/agents/agent.php gates its edit controls). */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/prompts.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/queries.php';

require_insider();

$pdo = db();
$id = request_integer('id');
if ($id === null || ($prompt = find_system_prompt($pdo, $id)) === null) {
    http_response_code(404);
    exit('Prompt not found.');
}

log_screen_view($pdo, 'system-prompt-view');
if (wants_json()) {
    require_once dirname(__DIR__, 3) . '/app/features/settings/present.php';
    $versions = find_system_prompt_versions($pdo, $id);
    $isHr = has_module($pdo, 'hr');
    respond_screen([
        'prompt' => present_system_prompt($prompt),
        'versions' => array_map('present_system_prompt_version', $versions),
        'used_by_count' => count_configs_citing_prompt($pdo, $id),
        // The New version form's prefill is sent only to someone who may write one.
        'new_version' => $isHr ? present_new_prompt_version_defaults($versions[0] ?? null) : null,
        'can' => ['write' => $isHr],
    ]);
}
render_screen(($prompt['name'] ?? 'Prompt') . ' · ' . business_name($pdo),
    view('settings/prompt.php', [
        'prompt' => $prompt,
        'versions' => find_system_prompt_versions($pdo, $id),
        'usedByCount' => count_configs_citing_prompt($pdo, $id),
        'isHr' => has_module($pdo, 'hr'),
        'errors' => [],
    ]),
    ['activeNav' => 'nav-settings', 'screen' => 'system-prompt-view', 'entity' => 'system_prompt', 'recordId' => (string) $id]);
