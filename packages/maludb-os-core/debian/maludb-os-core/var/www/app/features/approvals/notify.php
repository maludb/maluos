<?php
declare(strict_types=1);

/**
 * Telling people about approvals (build plan, phase 5 step 5: "the manager approval queue WITH
 * notifications"). The queue has existed since 2026-09-18 and raised nothing: an approver learned
 * of a request only by opening /approvals of their own accord, so an agent paused above threshold
 * at 07:00 could wait all day for a decision nobody knew was owed.
 *
 * In-app AND email, which is one call: notify_once() writes the notification row, and
 * bin/cron/notification_email_flush.php mails the unsent ones every five minutes. The kinds are
 * `approval_requested` and `approval_decided`, which db/041 reserved for this and which nothing
 * had ever written; neither has a preference column (kind_pref_column), so neither is opted out
 * of — a pending decision is business, not news.
 *
 * Nothing here may break the action it is reporting on. An approval that was recorded and not
 * announced is a delay; an approval lost because its notification failed is a defect.
 */

require_once dirname(__DIR__) . '/notifications/queries.php';

/** A member who can actually read a notification: active, human, not an agent. */
function approval_notifiable(PDO $pdo, ?int $memberId): bool
{
    if ($memberId === null) {
        return false;
    }
    $st = $pdo->prepare("SELECT 1 FROM members WHERE id = :m AND status = 'active' AND member_kind = 'human'");
    $st->execute(['m' => $memberId]);
    return $st->fetchColumn() !== false;
}

/**
 * Tell the approver that something is waiting for them. Called from create_approval_request()
 * (app/business.php) — the one place every paused action passes through, so no module can add a
 * pause and forget to announce it.
 */
function notify_approval_raised(PDO $pdo, int $requestId, int $approverId, string $summary,
                                ?string $amount, ?string $currency, string $requesterName): void
{
    try {
        if (!approval_notifiable($pdo, $approverId)) {
            return;
        }
        $money = ($amount !== null && $currency !== null) ? ' (' . $amount . ' ' . $currency . ')' : '';
        notify_once($pdo, $approverId, 'approval_requested', 'approval_request', $requestId,
            'Waiting for your decision: ' . $summary,
            $requesterName . ' asked for approval' . $money . '. Nothing has happened yet — it is waiting for you.');
    } catch (Throwable $e) {
        error_log('approval notify (raised): ' . $e->getMessage());
    }
}

/**
 * Tell whoever asked what was decided. An agent requester is skipped: its run ended when it was
 * paused, and `follow_up` on the decision screen is how an agent is told — by being run again
 * with the decision in its instructions (approvals_follow_up), not by a notification it can
 * never read.
 */
function notify_approval_decided(PDO $pdo, array $request, string $decision, ?string $note): void
{
    try {
        $requester = (int) $request['requested_by_member_id'];
        if (!approval_notifiable($pdo, $requester) || $requester === (int) current_member_id()) {
            return;   // nobody needs to be told what they just did themselves
        }
        $by = current_member()['display_name'] ?? 'your approver';
        $said = ($note !== null && trim($note) !== '') ? ' — ' . rtrim(trim($note), '.') : '';
        notify_once($pdo, $requester, 'approval_decided', 'approval_request', (int) $request['id'],
            ucfirst($decision) . ': ' . $request['summary'],
            $by . ' ' . $decision . ' it' . $said . '.');
    } catch (Throwable $e) {
        error_log('approval notify (decided): ' . $e->getMessage());
    }
}

/**
 * A withdrawn request is the mirror case: the approver was told to decide something, and the
 * thing has gone away. Without this their notification stands and they open an empty queue.
 */
function notify_approval_withdrawn(PDO $pdo, array $request): void
{
    try {
        $approver = $request['approver_member_id'] !== null ? (int) $request['approver_member_id'] : null;
        if (!approval_notifiable($pdo, $approver) || $approver === (int) current_member_id()) {
            return;
        }
        notify_once($pdo, $approver, 'approval_decided', 'approval_request', (int) $request['id'],
            'Withdrawn: ' . $request['summary'],
            (current_member()['display_name'] ?? 'The requester') . ' withdrew it. Nothing is waiting for you.');
    } catch (Throwable $e) {
        error_log('approval notify (withdrawn): ' . $e->getMessage());
    }
}
