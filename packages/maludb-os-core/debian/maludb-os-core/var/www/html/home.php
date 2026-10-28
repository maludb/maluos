<?php
declare(strict_types=1);

/**
 * Screen `app-home` (GET /home.php) — where app.<domain>/ takes the signed-in person (db/142;
 * docs/build-specs/kernel-default-application.md): straight into their default application, or the
 * only one they hold; otherwise the launcher. The React route /home asks this and redirects; the
 * launcher itself never redirects, so nothing can loop. ?app=<key>: an application sent the person here —
 * straight back into it when they hold it. JSON only (born after the cut-over).
 */
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/applications/queries.php';

require_login();
$pdo = db();
$member = find_member_by_id($pdo, (int) current_member_id()) ?? [];
$destination = ($member['member_kind'] ?? 'human') === 'human'
    ? app_home_destination($pdo, $member, (string) request_string('app'))
    : ['kind' => 'launcher', 'notice' => null];
respond_screen(['destination' => $destination]);
