<?php
declare(strict_types=1);

/**
 * Action `performance_review_create` — log `performance_review.create`. Gate: mod:hr, manager
 * (OR). Metrics are filled from records and activity (manifest) — see
 * review_metrics_for()'s docblock for exactly what is answerable before the prompt ledger and
 * agent runs exist.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/agents/render.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';
agents_require_files();

require_post();
verify_csrf();

$pdo = db();
$id = request_integer('member');
if ($id === null || ($member = find_team_member($pdo, $id)) === null) {
    http_response_code(404);
    exit('Member not found.');
}
if (!can_review_member($pdo, $member)) {
    deny('This needs the hr module grant, or being this person\'s manager.');
}

[$fields, $errors] = review_fields_from_request();

$renderForm = function (array $errs) use ($member): never {
    emit_action_status(false, ['errors' => $errs]);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    echo view('team/review-form.php', ['member' => $member, 'errors' => $errs]);
    exit;
};

if ($errors !== []) {
    $renderForm($errors);
}

check_approval($pdo, 'performance_review_create', 'performance_review.create',
    'Write a review for ' . $member['display_name'], $fields, 'member', $id);

try {
    $review = create_performance_review($pdo, $id, $fields, (int) current_member_id());
} catch (RuntimeException $ex) {
    $renderForm([$ex->getMessage()]);
}
if ($review === []) {
    $renderForm(['The review could not be saved.']);
}

log_activity($pdo, 'performance_review.create', 'member', $id, [
    'after' => ['period_start' => $review['period_start'], 'period_end' => $review['period_end'],
                'rating' => $review['rating']],
]);
emit_action_status(true, ['did' => 'Wrote a review for ' . $member['display_name'], 'refresh' => 'memberChanged']);
hx_trigger('memberChanged');

if (($member['member_kind'] ?? 'human') === 'agent') {
    render_agent_page($pdo, $id, 'performance');
}

header('HX-Retarget: #page-content');
header('HX-Reswap: innerHTML');
header('HX-Push-Url: /team/' . $id);
echo view('team/view.php', [
    'member' => $member,
    'departments' => member_departments($pdo, $id),
    'grants' => member_module_grants($pdo, $id),
    'modules' => grantable_modules(),
    'canAdmin' => can_admin_member($pdo, $id),
    'viewerTz' => current_member()['timezone'] ?? 'UTC',
]);
