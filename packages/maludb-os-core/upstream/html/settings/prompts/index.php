<?php
declare(strict_types=1);

/** The prompt library (screen `system-prompts`). Gate: insider — reading a prompt's text is no
 *  more sensitive than an agent's job description, which insiders already see; writes need
 *  mod:hr (system_prompt_save / system_prompt_version_create / system_prompt_archive). */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/prompts.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/queries.php';

require_insider();

$pdo = db();
$role = request_string('role') ?: null;
$prompts = find_system_prompts($pdo, true);
if ($role !== null) {
    $prompts = array_values(array_filter($prompts, static fn ($p) => ($p['role_key'] ?? null) === $role));
}

log_screen_view($pdo, 'system-prompts');
if (wants_json()) {
    require_once dirname(__DIR__, 3) . '/app/features/settings/present.php';
    respond_screen([
        'prompts' => array_map('present_system_prompt', $prompts),
        'filters' => ['role' => (string) $role],
        'can' => ['write' => has_module($pdo, 'hr')],
    ]);
}
render_screen('Prompt library · ' . business_name($pdo),
    view('settings/prompts.php', ['prompts' => $prompts, 'role' => $role, 'isHr' => has_module($pdo, 'hr'), 'errors' => []]),
    ['activeNav' => 'nav-settings', 'screen' => 'system-prompts']);
