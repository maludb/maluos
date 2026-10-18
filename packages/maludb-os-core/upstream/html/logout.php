<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/app/bootstrap.php';

// Logout must be POST + CSRF (a GET logout is a CSRF vector).
require_post();
verify_csrf();

$pdo = db();
// The applications this person signed in to from the launcher hear that they left (A3). Best
// effort, before the session that remembers them is gone.
$signedOn = $_SESSION['sso_apps'] ?? [];
if ($signedOn !== [] && current_member_id() !== null) {
    require_once dirname(__DIR__) . '/app/features/applications/sso.php';
    $notified = sso_logout_notices($pdo, (int) current_member_id(), $signedOn);
    log_activity($pdo, 'application.sign_off', 'member', (int) current_member_id(), ['after' => ['notified' => $notified]]);
}
logout($pdo);
redirect('/login.php');
