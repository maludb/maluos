<?php
declare(strict_types=1);

/** Skills — what is assigned to whom, and what agents have written that waits for a person. JSON only (React). */
require_once dirname(__DIR__, 2) . "/app/bootstrap.php";
require_once dirname(__DIR__, 2) . "/app/features/skills/maludb.php";
require_once dirname(__DIR__, 2) . "/app/features/skills/scan.php";
require_once dirname(__DIR__, 2) . "/app/features/skills/queries.php";
require_once dirname(__DIR__, 2) . "/app/features/skills/present.php";

require_insider();
$pdo = db();
$status = request_string('status') ?: 'proposed';
if (!in_array($status, ['proposed', 'approved', 'rejected', 'withdrawn', 'all'], true)) {
    $status = 'proposed';
}
$proposals = array_values(array_filter(list_skill_proposals($pdo, $status === 'all' ? null : $status),
    static fn (array $p): bool => (int) $p['agent_member_id'] === (int) current_member_id() || can_decide_skill_proposal($pdo, $p)));
log_screen_view($pdo, 'skills');
respond_screen([
    'assignments' => array_map('present_skill_assignment', list_skill_assignments($pdo)),
    'proposals' => array_map(static fn (array $p): array => present_skill_proposal($p), $proposals),
    'proposal_status' => $status,
    'can' => ['assign_anywhere' => !is_agent_member() && (is_super_admin() || has_module($pdo, 'hr')),
              'assign' => !is_agent_member() && (is_super_admin() || has_module($pdo, 'hr') || is_dept_admin())],
    'options' => skill_assign_options($pdo),
]);
