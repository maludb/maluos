<?php
declare(strict_types=1);

/**
 * Action `member_update` — log `member.update`. Gate: admin (app_can_admin_member — the super-admin, or
 * an admin of a department the person is in). A person's details as the operating system keeps them:
 * display_name, job_title, phone, timezone; only what is sent changes. People only — agents are
 * maintained in Agent HR. Undo: set the prior values (the log's `before`).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/team/maintain.php';

require_login();
require_post();
verify_csrf();

$pdo = db();
$memberId = request_integer('member');
$member = $memberId === null ? null : find_member_by_id($pdo, $memberId);
if ($member === null || ($member['member_kind'] ?? '') !== 'human') {
    emit_action_status(false, ['errors' => ['That person does not exist.']]);
    json_error('not_found', 'That person does not exist.', 404);
}
if (!can_admin_member($pdo, $memberId)) {
    emit_action_status(false, ['errors' => ['Only the super-admin, or an admin of their department, maintains a person.']]);
    json_error('forbidden', 'Only the super-admin, or an admin of their department, maintains a person.', 403);
}
[$fields, $errors] = member_detail_fields_from_request();
if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);
}
check_approval($pdo, 'member_update', 'member.update', 'Update ' . $member['display_name'],
    ['member' => $memberId] + $fields, 'member', $memberId);

$before = array_intersect_key($member, $fields);
update_member_details($pdo, $memberId, $fields);
log_activity($pdo, 'member.update', 'member', $memberId, ['before' => $before, 'after' => $fields]);
$did = 'Updated ' . ($fields['display_name'] ?? $member['display_name']);
emit_action_status(true, ['did' => $did, 'refresh' => 'memberChanged']);
respond_saved(['did' => $did, 'location' => '/team/' . $memberId]);
