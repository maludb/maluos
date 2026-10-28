<?php
declare(strict_types=1);

/** Action `skill_unassign` — withdraw an assignment. Same gate as assigning. Agents lose the skill at their next run. */
require_once dirname(__DIR__, 2) . "/app/bootstrap.php";
require_once dirname(__DIR__, 2) . "/app/features/skills/maludb.php";
require_once dirname(__DIR__, 2) . "/app/features/skills/scan.php";
require_once dirname(__DIR__, 2) . "/app/features/skills/queries.php";
require_once dirname(__DIR__, 2) . "/app/features/skills/present.php";

require_post();
verify_csrf();
require_insider();

$pdo = db();
$id = request_integer('skill_assignment');
$a = $id !== null ? find_skill_assignment($pdo, $id) : null;
if ($a === null || $a['revoked_at'] !== null) {
    http_response_code(404);
    emit_action_status(false, ['errors' => ['That assignment does not exist.']]);
    exit('That assignment does not exist.');
}
if (!can_assign_skill($pdo, $a['scope_kind'], $a['department_id'] !== null ? (int) $a['department_id'] : null,
        $a['agent_member_id'] !== null ? (int) $a['agent_member_id'] : null)) {
    deny('Withdrawing skills is for HR, or for a department\'s administrator inside that department.');
}
revoke_skill_assignment($pdo, (int) $a['id'], (int) current_member_id());
log_activity($pdo, 'skill.unassign', 'skill_assignment', (int) $a['id'], [
    'before' => ['skill_name' => $a['skill_name'], 'scope_kind' => $a['scope_kind']],
]);
emit_action_status(true, ['did' => 'Withdrew ' . $a['skill_name'] . ' (' . $a['scope_kind'] . ')', 'refresh' => 'skillsChanged']);
