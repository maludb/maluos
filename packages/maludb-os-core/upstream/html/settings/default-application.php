<?php
declare(strict_types=1);

/**
 * Action `member_default_application_set` — log `member.default_application_set`. Gate: own, or
 * whoever may administer the member (app_can_admin_member). The application app.<domain>/ opens for
 * them after sign-in (db/142), and on a scoped one the site or department. Only an application — and
 * scope — the member holds may be named; empty `application` clears it. Advice to the landing page,
 * never a grant. Undo: set the prior one (the log's `before`).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/applications/queries.php';

require_login();
require_post();
verify_csrf();

$pdo = db();
$refuse = static function (array $errors, int $status = 422): never {
    emit_action_status(false, ['errors' => $errors]);
    if ($status === 403) {
        json_error('forbidden', $errors[0], 403);
    }
    respond_invalid($errors);
};
$me = (int) current_member_id();
$memberId = request_integer('member') ?? $me;
if ($memberId !== $me && !can_admin_member($pdo, $memberId)) {
    $refuse(['Only the person, or someone who administers them, sets where they land.'], 403);
}
$member = find_member_by_id($pdo, $memberId);
if ($member === null || ($member['member_kind'] ?? 'human') !== 'human') {
    $refuse(['A default application is for a person.']);
}
$applicationId = request_integer('application');
$scopeId = request_integer('scope');
$options = member_default_application_options($pdo, $memberId);
$chosen = null;
foreach ($options as $o) {
    if ($o['id'] === $applicationId) {
        $chosen = $o;
    }
}
if ($applicationId !== null && $chosen === null) {
    $refuse([($memberId === $me ? 'You do' : 'They do') . ' not have access to that application.']);
}
if ($scopeId !== null && ($chosen === null || !in_array($scopeId, array_column($chosen['scopes'], 'id'), true))) {
    $refuse(['That site or department is not one ' . ($memberId === $me ? 'you hold' : 'they hold') . ' in this application.']);
}

$before = ['application_id' => $member['default_application_id'] ?? null, 'scope_id' => $member['default_scope_id'] ?? null];
$st = $pdo->prepare('UPDATE members SET default_application_id = :a, default_scope_id = :s, updated_at = now() WHERE id = :m');
$st->execute(['a' => $applicationId, 's' => $scopeId, 'm' => $memberId]);
log_activity($pdo, 'member.default_application_set', 'member', $memberId, [
    'before' => $before,
    'after' => ['application_id' => $applicationId, 'scope_id' => $scopeId],
]);
$scopeName = null;
foreach ($chosen['scopes'] ?? [] as $s) {
    if ($s['id'] === $scopeId) {
        $scopeName = $s['name'];
    }
}
$did = $chosen === null
    ? 'Cleared the default application for ' . $member['display_name']
    : $member['display_name'] . ' now opens ' . $chosen['name'] . ($scopeName !== null ? ' at ' . $scopeName : '') . ' after sign-in';
emit_action_status(true, ['did' => $did, 'refresh' => 'memberChanged']);
respond_saved(['did' => $did, 'location' => $memberId === $me ? '/settings' : '/team/' . $memberId]);
