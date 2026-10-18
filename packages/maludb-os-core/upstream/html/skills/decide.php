<?php
declare(strict_types=1);

/**
 * Action `skill_proposal_decide` — approve or reject a skill an agent wrote. Gate: HR, or the
 * author's nearest human manager; never an agent. Approve -> the bundle is ENABLED in MaluDB and
 * assigned to its author only (giving it to anyone else is a separate, deliberate skill_assign).
 * Reject -> it stays disabled; its text and the reason stay on the proposal.
 */
require_once dirname(__DIR__, 2) . "/app/bootstrap.php";
require_once dirname(__DIR__, 2) . "/app/features/skills/maludb.php";
require_once dirname(__DIR__, 2) . "/app/features/skills/scan.php";
require_once dirname(__DIR__, 2) . "/app/features/skills/queries.php";
require_once dirname(__DIR__, 2) . "/app/features/skills/present.php";

require_post();
verify_csrf();
require_insider();

$pdo = db();
$id = request_integer('skill_proposal');
$p = $id !== null ? find_skill_proposal($pdo, $id) : null;
if ($p === null) {
    http_response_code(404);
    emit_action_status(false, ['errors' => ['That proposal does not exist.']]);
    exit('That proposal does not exist.');
}
if (!can_decide_skill_proposal($pdo, $p)) {
    deny('A skill an agent wrote is decided by HR or by that agent\'s manager.');
}
$decision = request_string('decision');
$note = trim(request_string('note')) ?: null;
$errors = [];
if (!in_array($decision, ['approve', 'reject'], true)) {
    $errors[] = 'Approve or reject.';
}
if ($decision === 'reject' && $note === null) {
    $errors[] = 'Say why — the reason stays with the proposal.';
}
if ($p['status'] !== 'proposed') {
    $errors[] = 'That proposal is already ' . $p['status'] . '.';
}
if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);
}

if ($decision === 'approve') {
    // MaluDB first: a proposal marked approved whose skill is still disabled would be a lie.
    $error = maludb_skill_set_enabled((int) $p['maludb_skill_id'], true);
    if ($error !== null) {
        emit_action_status(false, ['errors' => [$error]]);
        respond_invalid([$error]);
    }
}
if (!decide_skill_proposal($pdo, (int) $p['id'], $decision === 'approve' ? 'approved' : 'rejected', (int) current_member_id(), $note)) {
    emit_action_status(false, ['errors' => ['Someone else decided that a moment ago.']]);
    respond_invalid(['Someone else decided that a moment ago.']);
}
$assignmentId = null;
if ($decision === 'approve') {
    [$row] = create_skill_assignment($pdo, [
        'skill_name' => $p['skill_name'], 'pinned_bundle_hash' => null, 'scope_kind' => 'agent', 'department_id' => null,
        'role_key' => null, 'agent_member_id' => (int) $p['agent_member_id'], 'note' => 'Written by this agent; approved proposal #' . $p['id'],
    ], (int) current_member_id());
    $assignmentId = $row !== null ? (int) $row['id'] : null;       // already assigned to its author: fine
}
log_activity($pdo, $decision === 'approve' ? 'skill.approve' : 'skill.reject', 'skill_proposal', (int) $p['id'], [
    'after' => ['skill_name' => $p['skill_name'], 'bundle_hash' => $p['bundle_hash'], 'author' => (int) $p['agent_member_id'],
                'note' => $note, 'skill_assignment_id' => $assignmentId],
]);
emit_action_status(true, ['did' => ($decision === 'approve' ? 'Approved ' : 'Rejected ') . $p['skill_name'] . ', written by ' . $p['agent_name'],
    'refresh' => 'skillsChanged']);
