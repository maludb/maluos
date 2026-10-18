<?php
declare(strict_types=1);

/**
 * Performance review form (screen `review-add`). Served as /team/reviews/new?member={id} —
 * the manifest's own three-segment-path correction (see the Agent HR build spec). Gate:
 * mod:hr, manager (OR).
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/render.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';
agents_require_files();

require_login();

$pdo = db();
$id = request_integer('member');
if ($id === null || ($member = find_team_member($pdo, $id)) === null) {
    http_response_code(404);
    exit('Member not found.');
}
if (!can_review_member($pdo, $member)) {
    deny('This needs the hr module grant, or being this person\'s manager.');
}

log_screen_view($pdo, 'review-add');
if (wants_json()) {
    respond_screen(['member' => ['id' => (int) $member['member_id'],
                                 'name' => (string) ($member['display_name'] ?? 'Member'),
                                 'kind' => (string) ($member['member_kind'] ?? 'human')]]);
}
render_screen('Write a review · ' . ($member['display_name'] ?? 'Member') . ' · ' . business_name($pdo),
    view('team/review-form.php', ['member' => $member, 'errors' => []]),
    ['activeNav' => 'nav-agents', 'screen' => 'review-add', 'entity' => 'member', 'recordId' => (string) $id]);
