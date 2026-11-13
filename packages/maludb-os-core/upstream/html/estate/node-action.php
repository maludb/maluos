<?php
declare(strict_types=1);

/**
 * Action `estate_node_action` — log `estate.node_action` (db/197; MaluOS Phase 14 slice 4d, maluos
 * docs/phase14-watching-agents.md). Ask a node of the estate to run one of its fixed verbs: restart_unit (a unit of
 * the node's own list), postgres_cancel / postgres_terminate (one backend by pid), apply_updates, reboot, or an
 * agent verb. Gate: a super-admin, or an agent of the IT department (the watching agents). An agent's request
 * pauses for its approver (the db/197 policy on `estate.node_action`); approved, it is replayed here and queued.
 *
 * The kernel queues; the NODE decides: it runs only what its own actions.allow permits and, for restart_unit,
 * only a unit of its own list. Nothing here is a shell or SQL of the caller's writing. The answer carries the
 * action's id; its outcome is read at /api/v1/estate/actions/ID or on the node's page.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/nodes.php';

require_login();
require_post();
verify_csrf();

$pdo = db();
$me = current_member();
$refuse = static function (string $message, int $status = 422): never {
    emit_action_status(false, ['errors' => [$message]]);
    if ($status === 403) { deny($message); }
    respond_invalid([$message]);
};

// Who may ask: a super-admin; an agent only when it works in IT.
if (is_agent_member()) {
    $st = $pdo->prepare("SELECT 1 FROM department_members dm JOIN departments d ON d.id = dm.department_id
                          WHERE dm.member_id = :m AND d.system_key = 'it' LIMIT 1");
    $st->execute(['m' => (int) $me['id']]);
    if ($st->fetchColumn() === false) { $refuse('Node actions are for the IT department\'s agents.', 403); }
} elseif (!is_super_admin()) {
    $refuse('Node actions are a super-admin\'s, or an IT agent\'s with approval.', 403);
}

$nodeId = request_integer('location');
$node = $nodeId !== null ? node_row($pdo, $nodeId) : [];
if ($node === [] || ($node['status'] ?? '') !== 'active' || !in_array($node['kind'] ?? '', NODE_KINDS, true)) {
    $refuse('No such node: location is an active server or inference node of the estate.');
}
$action = trim(request_string('action'));
$agent = trim(request_string('agent')) ?: null;
$reason = mb_substr(trim(request_string('reason')), 0, 300);
$checked = action_args($action, $agent, ['unit' => trim(request_string('unit')) ?: null, 'pid' => trim(request_string('pid')) ?: null]);
if (is_string($checked)) { $refuse($checked); }
[$args, $agent] = $checked;
if ($reason === '') { $refuse('reason says why, in a sentence: the approver and the node\'s record read it.'); }

$what = match ($action) {
    'restart_unit' => 'restart ' . $args['unit'],
    'postgres_cancel' => 'cancel the statement of PostgreSQL backend ' . $args['pid'],
    'postgres_terminate' => 'end the session of PostgreSQL backend ' . $args['pid'],
    'apply_updates' => 'apply pending updates',
    'reboot' => 'reboot',
    default => str_replace('_', ' ', $action) . ' ' . $agent,
};
$summary = ucfirst($what) . ' on ' . $node['name'] . ': ' . $reason;

check_approval($pdo, 'estate_node_action', 'estate.node_action', $summary,
    ['location' => (int) $node['id'], 'action' => $action, 'unit' => $args['unit'] ?? null, 'pid' => $args['pid'] ?? null, 'agent' => $agent, 'reason' => $reason],
    'location', (int) $node['id']);

$pdo->beginTransaction();
$a = action_create_kernel($pdo, $node, $action, $agent, $args, $me, isset($GLOBALS['__approval_replay_id']) ? (int) $GLOBALS['__approval_replay_id'] : null, $summary);
$pdo->commit();
log_activity($pdo, 'estate.node_action', 'location', (int) $node['id'], [
    'after' => ['action' => $action, 'args' => $args, 'agent' => $agent, 'reason' => $reason, 'id' => $a['id'], 'approval_request_id' => $a['approval_request_id'] ?? null],
]);
emit_action_status(true, ['did' => 'Asked ' . $node['name'] . ' to ' . $what . ' (' . $a['id'] . ')', 'record_id' => $a['id']]);
respond_saved(['action' => present_action($a)]);
