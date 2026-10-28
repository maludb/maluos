<?php
declare(strict_types=1);

/**
 * Action `skill_assign` — give a MaluDB skill to the organisation, a department, a functional role,
 * one agent or an application (db/130: it reaches the application's expert and every agent that
 * may use it), optionally pinned to a bundle hash. Gate: HR anywhere; a dept-admin inside the
 * departments they administer; mod:applications for an application; never an agent. The skill must exist and be enabled in MaluDB, and a
 * pin must resolve — an assignment to something that is not there would silently give nobody anything.
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
$f = [
    'skill_name' => trim(request_string('skill_name')), 'scope_kind' => request_string('scope_kind'),
    'department_id' => request_integer('department'), 'role_key' => trim(request_string('role_key')) ?: null,
    'agent_member_id' => request_integer('agent'), 'application_id' => request_integer('application'),
    'pinned_bundle_hash' => trim(request_string('pinned_bundle_hash')) ?: null,
    'note' => trim(request_string('note')) ?: null,
];
$errors = [];
if (!preg_match(SKILL_NAME_PATTERN, $f['skill_name'])) {
    $errors[] = 'Name the skill (lower-case letters, digits and hyphens).';
}
if (!in_array($f['scope_kind'], SKILL_SCOPES, true)) {
    $errors[] = 'Assign it to the organisation, a department, a role, one agent or an application.';
} else {
    $need = ['org' => null, 'department' => 'department_id', 'role' => 'role_key', 'agent' => 'agent_member_id',
             'application' => 'application_id'][$f['scope_kind']];
    foreach (['department_id', 'role_key', 'agent_member_id', 'application_id'] as $k) {
        if ($k !== $need) {
            $f[$k] = null;                       // only the field the scope names is kept
        }
    }
    if ($need !== null && $f[$need] === null) {
        $errors[] = 'Say which ' . ['department_id' => 'department', 'role_key' => 'role', 'agent_member_id' => 'agent',
                                     'application_id' => 'application'][$need] . '.';
    }
    if ($f['application_id'] !== null) {
        // Skills belong to an application that runs: a planned or retired one has nobody to reach.
        $st = $pdo->prepare("SELECT 1 FROM mcp_applications WHERE application_id = :a AND status IN ('active', 'degraded')");
        $st->execute(['a' => $f['application_id']]);
        if ($st->fetchColumn() === false) {
            $errors[] = 'Skills can be given to an active application only.';
        }
    }
}
if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);
}
if (!can_assign_skill($pdo, $f['scope_kind'], $f['department_id'], $f['agent_member_id'])) {
    deny($f['scope_kind'] === 'application'
        ? 'An application\'s skills are set by HR or by whoever holds the Applications grant.'
        : 'Assigning skills is for HR, or for a department\'s administrator inside that department.');
}
[$skill, $error] = maludb_skill_resolve($f['skill_name'], $f['pinned_bundle_hash']);
if ($error !== null || $skill === null || ($f['pinned_bundle_hash'] === null && empty($skill['enabled']))) {
    $why = [$error ?? ('There is no ' . ($f['pinned_bundle_hash'] ? 'such version of' : 'enabled skill called') . ' "' . $f['skill_name'] . '" in MaluDB.')];
    emit_action_status(false, ['errors' => $why]);
    respond_invalid($why);
}
[$row, $error] = create_skill_assignment($pdo, $f, (int) current_member_id());
if ($error !== null) {
    emit_action_status(false, ['errors' => [$error]]);
    respond_invalid([$error]);
}
log_activity($pdo, 'skill.assign', 'skill_assignment', (int) $row['id'], [
    'after' => ['skill_name' => $f['skill_name'], 'scope_kind' => $f['scope_kind'], 'department_id' => $f['department_id'],
                'role_key' => $f['role_key'], 'agent_member_id' => $f['agent_member_id'], 'application_id' => $f['application_id'],
                'pinned_bundle_hash' => $f['pinned_bundle_hash']],
]);
emit_action_status(true, ['did' => 'Assigned ' . $f['skill_name'] . ' (' . $f['scope_kind'] . ')', 'skill_assignment_id' => (int) $row['id'], 'refresh' => 'skillsChanged']);
