<?php
declare(strict_types=1);

/** Screens `eval-set-add` (params: agent, role) and the set's edit form. mod:evals. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/records/present.php';

$pdo = db();
aiops_require_evals($pdo);
$id = request_integer('id');
$set = null;
if ($id !== null && ($set = find_eval_set($pdo, $id)) === null) {
    http_response_code(404);
    exit('Eval set not found.');
}
log_screen_view($pdo, 'eval-set-add');
$named = static fn (array $l): array => array_map(static fn (string $k, string $v): array => ['id' => $k, 'name' => $v], array_keys($l), $l);
respond_screen([
    'set' => present_eval_set($set ?? ['agent_member_id' => request_integer('agent'), 'role_key' => mb_substr(request_string('role'), 0, 80) ?: null, 'status' => 'active', 'pass_threshold' => '80']),
    'options' => ['agents' => array_values(array_filter(array_map('present_member_option', selectable_members($pdo)), static fn (array $m): bool => $m['kind'] === 'agent')),
                  'departments' => array_map('present_department_option', find_departments($pdo)), 'statuses' => $named(EVAL_SET_STATUSES)],
]);
