<?php
declare(strict_types=1);

/**
 * Re-issue a pending invitation's link, for an operator (and the smoke, which cannot read mail):
 *
 *   php bin/invitation_link.php <invitation-id>
 *
 * The raw token is never stored, so a link can only be RE-issued: this replaces the token, and the
 * link in the original email stops working. Prints the new link. Logged as `invitation.resend`.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }

require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/invitations/queries.php';

$id = (int) ($argv[1] ?? 0);
$pdo = db();
$raw = $id > 0 ? resend_invitation($pdo, $id) : null;
if ($raw === null) { fwrite(STDERR, "No pending invitation with that id.\n"); exit(2); }
log_activity($pdo, 'invitation.resend', 'invitation', $id, ['source' => 'cron', 'after' => ['by' => 'bin/invitation_link.php']]);
echo app_url('/register?token=' . $raw), "\n";
