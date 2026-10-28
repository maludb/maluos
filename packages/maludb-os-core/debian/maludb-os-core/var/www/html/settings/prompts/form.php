<?php
declare(strict_types=1);

/** New prompt form (screen `system-prompt-add`). Gate: mod:hr — this is the write surface's
 *  entry, same reasoning as html/agents/form.php for the hire form. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/prompts.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/queries.php';

require_module_grant('hr');

$pdo = db();
log_screen_view($pdo, 'system-prompt-add');
if (wants_json()) {
    respond_screen(['ready' => true]);
}
render_screen('New prompt · ' . business_name($pdo),
    view('settings/prompt-form.php', ['prompt' => [], 'errors' => []]),
    ['activeNav' => 'nav-settings', 'screen' => 'system-prompt-add']);
