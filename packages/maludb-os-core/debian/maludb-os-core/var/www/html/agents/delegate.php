<?php
declare(strict_types=1);

/**
 * Action `agent_delegate` — an orchestrator hands a piece of work to a subagent on its roster.
 * Gate, all of it: the caller is an AGENT INSIDE A RUN (a run token — no person and no assistant
 * token delegates), its kind is `orchestrator`, and the named subagent is on its live roster and
 * active. The roster is a tree (db/154): an orchestrator may hand work to an orchestrator below it.
 * The work runs as the SUBAGENT — its own identity, grants, budget, memory and ledger rows — with
 * parent_run_id pointing here, so the delegation is visible as a family of runs, never as an
 * anonymous child. A one-shot run cannot wait: when the family completes the runner starts a
 * continuation for the orchestrator with what came back (mcp/agent_runner/scheduler.py).
 *
 * Since db/154 the roster is a TREE: the subagent may itself be an orchestrator (a department lead
 * under an assistant). Every delegation records where it went and why (`reason`, `department`); a
 * personal assistant must give a reason and cannot hand work outside its person's departments.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_post();
verify_csrf();
require_insider();

$pdo = db();
$me = (int) current_member_id();
$runId = current_agent_run_id();
$fail = static function (array $errors, int $status = 422): never {
    http_response_code($status);
    emit_action_status(false, ['errors' => $errors, 'error' => implode(' ', $errors)]);
    echo e(implode(' ', $errors));
    exit;
};
if (!is_agent_member() || $runId === null) {
    $fail(['Only an agent, inside one of its own runs, can delegate.'], 403);
}
$orchestrator = find_agent($pdo, $me);
if ($orchestrator === null || ($orchestrator['agent_kind'] ?? '') !== 'orchestrator') {
    $fail(['Only an orchestrator can delegate; you do the work yourself.'], 403);
}

$named = trim(request_string('subagent'));
$instructions = trim(request_string('instructions'));
// Routing records (db/154): where the work goes and why. A personal assistant must say why.
$reason = trim(request_string('reason'));
$departmentNamed = trim(request_string('department'));
$st = $pdo->prepare('SELECT principal_member_id FROM agent_profiles WHERE member_id = :m');
$st->execute(['m' => $me]);
$isAssistant = $st->fetchColumn() !== null;
$errors = [];
if ($isAssistant && mb_strlen($reason) < 10) {
    $errors[] = 'Say why this agent is the right one (reason) — your person sees every hand-off and its reason.';
} elseif (mb_strlen($reason) > 2000) {
    $errors[] = 'Keep the reason under 2,000 characters.';
}
if ($named === '') {
    $errors[] = 'Say which subagent.';
}
if ($instructions === '') {
    $errors[] = 'Say what the subagent should do — it starts with no knowledge of your conversation.';
} elseif (strlen($instructions) > AGENT_RUN_INSTRUCTIONS_MAX) {
    $errors[] = 'The instructions are too long.';
}
if ($errors !== []) {
    $fail($errors);
}
$subagent = find_roster_subagent($pdo, $me, $named);
if ($subagent === null) {
    $fail(['"' . $named . '" is not on your roster. You can delegate to: ' . (implode(', ', roster_names($pdo, $me)) ?: 'nobody yet') . '.'], 403);
}

// Where it lands: the subagent's departments; the one named, else its primary. An assistant never
// reaches further than its person (app_agent_reach_department_ids(), db/154) — unless the agent it
// hands to is itself someone's assistant, placed under it by a super-admin.
$st = $pdo->prepare('SELECT dm.department_id, d.name::text AS name, dm.is_primary FROM department_members dm
                       JOIN departments d ON d.id = dm.department_id
                      WHERE dm.member_id = :m AND dm.left_at IS NULL ORDER BY dm.is_primary DESC, d.name');
$st->execute(['m' => (int) $subagent['member_id']]);
$childDepartments = $st->fetchAll();
$department = $childDepartments[0] ?? null;
if ($departmentNamed !== '') {
    $department = null;
    foreach ($childDepartments as $d) {
        if ((string) $d['department_id'] === $departmentNamed || strcasecmp((string) $d['name'], $departmentNamed) === 0) {
            $department = $d;
        }
    }
    if ($department === null) {
        $fail([$subagent['display_name'] . ' does not work in "' . $departmentNamed . '". It works in: '
            . (implode(', ', array_column($childDepartments, 'name')) ?: 'no department') . '.']);
    }
}
$st = $pdo->prepare('SELECT app_agent_reach_department_ids(:me) AS reach,
                            (SELECT principal_member_id FROM agent_profiles WHERE member_id = :child) AS child_principal');
$st->execute(['me' => $me, 'child' => (int) $subagent['member_id']]);
$reachRow = $st->fetch();
if ($reachRow['reach'] !== null && $reachRow['child_principal'] === null) {
    $reach = array_map('intval', array_filter(explode(',', trim((string) $reachRow['reach'], '{}')), 'strlen'));
    $inReach = array_values(array_filter($childDepartments, static fn (array $d): bool => in_array((int) $d['department_id'], $reach, true)));
    if ($inReach === []) {
        $fail([$subagent['display_name'] . ' works outside the departments your person runs — you cannot hand work there.'], 403);
    }
    if ($department !== null && !in_array((int) $department['department_id'], $reach, true)) {
        $department = $inReach[0];
    }
}

[$run, $error] = start_agent_run((int) $subagent['member_id'], $instructions, 'delegation', null, $me, $runId);
if ($error !== null) {
    $fail([$subagent['display_name'] . ' could not take it: ' . $error], 409);
}
$pdo->prepare('UPDATE agent_runs SET delegated_department_id = :d, delegation_reason = :r WHERE id = :id')
    ->execute(['d' => $department['department_id'] ?? null, 'r' => $reason !== '' ? $reason : null, 'id' => (int) $run['run_id']]);
log_activity($pdo, 'agent_run.delegate', 'member', (int) $subagent['member_id'], [
    'after' => ['run_id' => (int) $run['run_id'], 'parent_run_id' => $runId, 'subagent' => $subagent['display_name'],
                'department' => $department['name'] ?? null, 'reason' => $reason !== '' ? $reason : null],
]);
emit_action_status(true, [
    'did' => 'Delegated to ' . $subagent['display_name'] . ' as run #' . (int) $run['run_id']
        . '. You cannot wait for it: finish what you can now. When it ends you will be started again with its answer.',
    'run_id' => (int) $run['run_id'],
]);
