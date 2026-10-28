<?php
declare(strict_types=1);
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/settings/queries.php';
require_login(); require_post(); verify_csrf();
$pdo = db(); $me = (int) current_member_id();
$name = request_string('display_name'); $tz = request_string('timezone', 'UTC');
$bio = request_string('bio'); $org = request_string('organization');
$jobTitle = request_string('job_title'); $phone = request_string('phone');
if ($name === '' || !in_array($tz, timezone_identifiers_list(), true)) {
    emit_action_status(false, ['errors' => ['A display name and a valid timezone are required.']]);
    echo settings_section_html($pdo, $me, 'profile', ['notice' => '']); exit;
}
update_profile($pdo, $me, $name, $tz, $bio, $org, $jobTitle ?: null, $phone ?: null);
emit_action_status(true, ['did' => 'Profile saved']);
log_activity($pdo, 'member.update', 'member', $me, ['after' => ['profile' => true]]);
echo settings_section_html($pdo, $me, 'profile', ['notice' => 'Profile saved.']);
