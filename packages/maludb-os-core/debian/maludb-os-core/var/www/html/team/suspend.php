<?php
declare(strict_types=1);

/**
 * Action `member_suspend` — log `member.suspend`. Gate: super. The person can no longer sign in to the
 * kernel or open any application (they hold nothing while suspended), and every application's mirror
 * hears it within a minute. Nothing is deleted: reinstating restores exactly what they had. Never
 * yourself, never an agent (Agent HR suspends agents), never the last active super-admin.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/team/maintain.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$refuse = static function (string $message): never {
    emit_action_status(false, ['errors' => [$message]]);
    respond_invalid([$message]);
};
$memberId = request_integer('member');
$member = $memberId === null ? null : find_member_by_id($pdo, $memberId);
if ($member === null || ($member['member_kind'] ?? '') !== 'human') {
    $refuse('That person does not exist — an agent is suspended in Agent HR.');
}
if ($memberId === (int) current_member_id()) {
    $refuse('You cannot suspend yourself.');
}
if ($member['business_role'] === 'super_admin' && other_active_super_admins($pdo, $memberId) === 0) {
    $refuse('They are the only active super-admin — the business would have no one to run the operating system.');
}
$reason = trim(request_string('reason')) ?: null;
check_approval($pdo, 'member_suspend', 'member.suspend', 'Suspend ' . $member['display_name'],
    ['member' => $memberId, 'reason' => $reason], 'member', $memberId);
if (!set_member_status($pdo, $memberId, 'active', 'suspended')) {
    $refuse($member['display_name'] . ' is ' . $member['status'] . ', not active.');
}
log_activity($pdo, 'member.suspend', 'member', $memberId, ['before' => ['status' => 'active'], 'after' => ['status' => 'suspended', 'reason' => $reason]]);
$did = 'Suspended ' . $member['display_name'];
emit_action_status(true, ['did' => $did, 'refresh' => 'memberChanged']);
respond_saved(['did' => $did, 'location' => '/team/' . $memberId]);
