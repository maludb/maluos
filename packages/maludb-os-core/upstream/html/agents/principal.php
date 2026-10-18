<?php
declare(strict_types=1);

/**
 * Action `agent_principal_set` — log `agent.principal_set`. Gate: super; never an agent.
 *
 * Makes an orchestrator a person's PERSONAL ASSISTANT (db/154), or — with no `person` — ends that. The
 * assistant is the only agent that talks to its person, always delegates, and never reaches further
 * than its person: it may hand work only into the departments that person runs (every department for a
 * super-admin). One assistant per person; the agent must already be an orchestrator. The trigger's own
 * sentences refuse the rest (not a person, not active, not an orchestrator).
 * Born after the cut-over: no template, so a refusal says its own words (respond_invalid).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_super_admin();
agent_refuse_agent_caller();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    emit_action_status(false, ['errors' => ['Agent not found.']]);
    json_error('not_found', 'Agent not found.', 404);
}
$person = request_integer('person');
$refuse = static function (string $why): never {
    emit_action_status(false, ['errors' => [$why]]);
    respond_invalid([$why]);
};
$st = $pdo->prepare('SELECT principal_member_id FROM agent_profiles WHERE member_id = :id');
$st->execute(['id' => $id]);
$before = $st->fetchColumn();
$before = $before === false || $before === null ? null : (int) $before;
if ($person === $before) {
    $refuse($agent['display_name'] . ($person === null ? ' is nobody\'s assistant already.' : ' is already that person\'s assistant.'));
}
$personName = null;
if ($person !== null) {
    $st = $pdo->prepare('SELECT display_name FROM members WHERE id = :id');
    $st->execute(['id' => $person]);
    $personName = $st->fetchColumn() ?: null;
    if ($personName === null) {
        $refuse('That person does not exist.');
    }
}

check_approval($pdo, 'agent_principal_set', 'agent.principal_set',
    $person === null ? 'End ' . $agent['display_name'] . ' as a personal assistant' : 'Make ' . $agent['display_name'] . ' the assistant of ' . $personName,
    ['agent' => $id, 'person' => $person], 'member', $id);

try {
    $pdo->prepare('UPDATE agent_profiles SET principal_member_id = :p, updated_at = now() WHERE member_id = :id')
        ->execute(['p' => $person, 'id' => $id]);
} catch (PDOException $ex) {
    $why = $ex->getCode() === '23505' ? ($personName . ' already has an assistant — end that one first.')
        : agent_trigger_message($ex, 'The assistant could not be set.');
    $refuse($why);
}
log_activity($pdo, 'agent.principal_set', 'member', $id, ['before' => ['principal_member_id' => $before], 'after' => ['principal_member_id' => $person]]);
emit_action_status(true, ['did' => $person === null ? $agent['display_name'] . ' is no longer anyone\'s assistant'
    : $agent['display_name'] . ' is now the personal assistant of ' . $personName, 'refresh' => 'agentChanged']);
hx_trigger('agentChanged');
