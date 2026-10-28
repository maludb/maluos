<?php
declare(strict_types=1);

/** Action `eval_set_save` — create or change an eval set (for one agent, or for a role). mod:evals; never an agent. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';

require_post();
verify_csrf();

$pdo = db();
aiops_require_evals($pdo);
$id = request_integer('eval_set');
$before = null;
if ($id !== null) {
    if (find_eval_set($pdo, $id) === null) { aiops_refuse(['Eval set not found.'], 404); }
    $b = $pdo->prepare('SELECT name, description, agent_member_id, role_key, department_id, pass_threshold, status FROM eval_sets WHERE id = :id');
    $b->execute(['id' => $id]);
    $before = $b->fetch() ?: null;
}
$has = static fn (string $k): bool => array_key_exists($k, $_POST);
$f = [
    'name' => mb_substr(trim(request_string('name')), 0, 160),
    'description' => $has('description') || $before === null ? (mb_substr(trim((string) ($_POST['description'] ?? '')), 0, 4000) ?: null) : $before['description'],
    'agent' => $has('agent') || $before === null ? request_integer('agent') : $before['agent_member_id'],
    'role_key' => $has('role_key') || $before === null ? (mb_substr(trim(request_string('role_key')), 0, 80) ?: null) : $before['role_key'],
    'department' => $has('department') || $before === null ? request_integer('department') : $before['department_id'],
    'threshold' => $has('pass_threshold') ? request_string('pass_threshold') : (string) ($before['pass_threshold'] ?? '80'),
    'status' => $has('status') ? request_string('status') : (string) ($before['status'] ?? 'active'),
];
$errors = [];
if ($f['name'] === '') { $errors[] = 'An eval set needs a name.'; }
if ($f['agent'] === null && $f['role_key'] === null) { $errors[] = 'Say which agent the set is for, or which role.'; }
if (!is_numeric($f['threshold']) || (float) $f['threshold'] < 0 || (float) $f['threshold'] > 100) { $errors[] = 'The pass threshold is a score from 0 to 100.'; }
if (!isset(EVAL_SET_STATUSES[$f['status']])) { $errors[] = 'A set is draft, active or retired.'; }
if ($f['agent'] !== null) {
    $st = $pdo->prepare("SELECT 1 FROM mcp_team_directory WHERE member_id = :m AND member_kind = 'agent'");
    $st->execute(['m' => (int) $f['agent']]);
    if ($st->fetchColumn() === false) { $errors[] = 'That agent does not exist.'; }
}
if ($f['department'] !== null) {
    $st = $pdo->prepare('SELECT 1 FROM mcp_departments WHERE department_id = :d');
    $st->execute(['d' => (int) $f['department']]);
    if ($st->fetchColumn() === false) { $errors[] = 'That department does not exist.'; }
}
// Trace checks (db/145): the JEV checks the Auditor applies to sampled REAL runs of the set's agent.
$traceChecks = null;
$traceSent = array_key_exists('trace_checks', $_POST);
if ($traceSent && trim((string) $_POST['trace_checks']) !== '') {
    [$tc, $tcErrors] = eval_jev_checks_from_json((string) $_POST['trace_checks']);
    $errors = array_merge($errors, array_map(static fn (string $e): string => 'Trace checks: ' . $e, $tcErrors));
    $traceChecks = $tc !== null ? json_encode($tc, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) : null;
}
if ($errors !== []) { aiops_refuse($errors); }
$args = ['n' => $f['name'], 'd' => $f['description'], 'a' => $f['agent'], 'r' => $f['role_key'], 'dep' => $f['department'], 't' => $f['threshold'], 's' => $f['status']];
if ($id === null) {
    $st = $pdo->prepare('INSERT INTO eval_sets (name, description, agent_member_id, role_key, department_id, pass_threshold, status, created_by) VALUES (:n, :d, :a, :r, :dep, :t, :s, :by) RETURNING id');
    $st->execute($args + ['by' => (int) current_member_id()]);
    $id = (int) $st->fetchColumn();
    if ($traceSent) { $pdo->prepare('UPDATE eval_sets SET trace_checks = :c::jsonb WHERE id = :id')->execute(['c' => $traceChecks, 'id' => $id]); }
} else {
    $pdo->prepare('UPDATE eval_sets SET name = :n, description = :d, agent_member_id = :a, role_key = :r, department_id = :dep, pass_threshold = :t, status = :s, updated_at = now() WHERE id = :id')->execute($args + ['id' => $id]);
    if ($traceSent) { $pdo->prepare('UPDATE eval_sets SET trace_checks = :c::jsonb WHERE id = :id')->execute(['c' => $traceChecks, 'id' => $id]); }
}
log_activity($pdo, 'eval_set.save', 'eval_set', $id, ['before' => $before, 'after' => ['name' => $f['name'], 'agent_member_id' => $f['agent'], 'role_key' => $f['role_key'], 'department_id' => $f['department'], 'pass_threshold' => $f['threshold'], 'status' => $f['status']]]);
emit_action_status(true, ['did' => ($before === null ? 'Created eval set ' : 'Saved eval set ') . $f['name'], 'refresh' => 'aiopsChanged']);
header('HX-Push-Url: /ai/evals/' . $id);
