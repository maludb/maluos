<?php
declare(strict_types=1);

/** Screen `eval-watch` — the Audit department's watch: standing schedules and open degradation alerts (params: agent, eval_set, severity, status — click-around step 4: the agent applies to schedules too, and a set's page can point here). */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/records/present.php';

require_insider();
if (is_agent_member()) { deny('Evals are people\'s work — an agent cannot open them.'); }

$pdo = db();
log_screen_view($pdo, 'eval-watch');
$filters = ['agent' => request_integer('agent'), 'eval_set' => request_integer('eval_set'), 'severity' => request_string('severity'), 'status' => request_string('status')];
respond_screen(['schedules' => array_map('present_eval_schedule', find_eval_schedules($pdo, $filters['eval_set'], $filters['agent'])), 'alerts' => array_map('present_eval_alert', find_eval_alerts($pdo, $filters)),
    'filters' => $filters, 'runner_built' => true, 'can' => ['write' => has_module_grant('evals')],
    'options' => ['agents' => array_values(array_filter(array_map('present_member_option', selectable_members($pdo)), static fn (array $m): bool => $m['kind'] === 'agent')),
                  'sets' => array_map(static fn (array $s): array => ['id' => (int) $s['eval_set_id'], 'name' => (string) $s['name']], find_eval_sets($pdo))]]);
