<?php
declare(strict_types=1);

/** One skill proposal with both SKILL.md texts, for the reviewer's diff. JSON only (React). */
require_once dirname(__DIR__, 3) . "/app/bootstrap.php";
require_once dirname(__DIR__, 3) . "/app/features/skills/maludb.php";
require_once dirname(__DIR__, 3) . "/app/features/skills/scan.php";
require_once dirname(__DIR__, 3) . "/app/features/skills/queries.php";
require_once dirname(__DIR__, 3) . "/app/features/skills/present.php";

require_insider();
$pdo = db();
$id = request_integer('skill_proposal') ?? request_integer('id');
$p = $id !== null ? find_skill_proposal($pdo, $id) : null;
if ($p === null) {
    json_error('not_found', 'That proposal does not exist.', 404);
}
if ((int) $p['agent_member_id'] !== (int) current_member_id() && !can_decide_skill_proposal($pdo, $p)) {
    deny('A proposal is read by its author, the author\'s manager, or HR.');
}
log_screen_view($pdo, 'skill-proposal');
respond_screen(['proposal' => present_skill_proposal($p, true), 'can' => ['decide' => can_decide_skill_proposal($pdo, $p) && $p['status'] === 'proposed']]);
