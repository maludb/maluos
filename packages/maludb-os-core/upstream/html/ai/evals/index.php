<?php
declare(strict_types=1);

/** Screen `eval-sets` — eval sets per agent or role (params: agent, status). People only; mcp_eval_sets shows the evals grant everything and a manager their agents' sets. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/records/present.php';

require_insider();
if (is_agent_member()) { deny('Evals are people\'s work — an agent cannot open them.'); }

$pdo = db();
log_screen_view($pdo, 'eval-sets');
respond_screen([
    'sets' => array_map('present_eval_set', find_eval_sets($pdo, request_integer('agent'), request_string('status'))),
    'filters' => ['agent' => request_integer('agent'), 'status' => request_string('status')],
    'runner_built' => true, 'runner_note' => EVAL_RUNNER_NOTE,
    'options' => ['agents' => array_values(array_filter(array_map('present_member_option', selectable_members($pdo)), static fn (array $m): bool => $m['kind'] === 'agent'))],
    'can' => ['write' => has_module_grant('evals')],
]);
