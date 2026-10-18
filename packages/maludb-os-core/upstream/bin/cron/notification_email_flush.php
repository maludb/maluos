<?php
declare(strict_types=1);
// Every 5 min: email unsent notifications to members who opted in. Marks each handled so
// it is never re-sent (there is no MaluMail idempotency key).
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/notifications/queries.php';

$pdo = db();
$sent = 0; $skipped = 0;
$linkFor = static function (array $n): string {
    // React routes for anything born after the cut-over; the three cert-study screens keep
    // their PHP paths. A notification whose link is "/" makes the reader hunt for what it is
    // about — which is what every business notification did until 2026-09-20.
    $id = (int) $n['entity_id'];
    return match ($n['entity_type']) {
        'approval_request' => app_url('/approvals/' . $id),
        'content_item'     => app_url('/content/' . $id),
        'form_submission'  => app_url('/forms/submissions/' . $id),
        'study_issue'      => app_url('/issues/view.php?id=' . $id),
        'study_plan'       => app_url('/plans/view.php?id=' . $id),
        'community_event'  => app_url('/events/view.php?id=' . $id),
        default => app_url('/'),
    };
};
foreach (unsent_notifications($pdo, 100) as $n) {
    $prefCol = kind_pref_column($n['kind']);
    $allowed = $prefCol === null || in_array((string) $n[$prefCol], ['1', 't', 'true'], true);
    if ($allowed) {
        send_email($n['email'], $n['title'], 'notification', ['title' => $n['title'], 'body' => $n['body'], 'url' => $linkFor($n)]);
        $sent++;
    } else {
        $skipped++;
    }
    mark_notification_emailed($pdo, (int) $n['id']);   // mark handled either way (never retry)
}
log_activity($pdo, 'cron.run', null, null, ['source' => 'cron', 'after' => ['job' => 'notification_email_flush', 'sent' => $sent, 'skipped' => $skipped]]);
echo "notification_email_flush: sent {$sent}, skipped {$skipped}\n";
