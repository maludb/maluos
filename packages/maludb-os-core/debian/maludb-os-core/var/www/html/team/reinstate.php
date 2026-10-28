<?php
declare(strict_types=1);

/**
 * Action `member_reinstate` — log `member.reinstate`. Gate: super. A suspended person is active again:
 * they sign in and hold exactly the grants they held before (nothing was revoked by the suspension).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/team/maintain.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$memberId = request_integer('member');
$member = $memberId === null ? null : find_member_by_id($pdo, $memberId);
if ($member === null || ($member['member_kind'] ?? '') !== 'human') {
    emit_action_status(false, ['errors' => ['That person does not exist.']]);
    respond_invalid(['That person does not exist.']);
}
check_approval($pdo, 'member_reinstate', 'member.reinstate', 'Reinstate ' . $member['display_name'],
    ['member' => $memberId], 'member', $memberId);
if (!set_member_status($pdo, $memberId, 'suspended', 'active')) {
    emit_action_status(false, ['errors' => [$member['display_name'] . ' is not suspended.']]);
    respond_invalid([$member['display_name'] . ' is not suspended.']);
}
log_activity($pdo, 'member.reinstate', 'member', $memberId, ['before' => ['status' => 'suspended'], 'after' => ['status' => 'active']]);
$did = 'Reinstated ' . $member['display_name'];
emit_action_status(true, ['did' => $did, 'refresh' => 'memberChanged']);
respond_saved(['did' => $did, 'location' => '/team/' . $memberId]);
