<?php
declare(strict_types=1);

/**
 * Notification + reminder query helpers (used by the cron jobs and by feature handlers).
 * Reminders are idempotent: notify_once refuses a duplicate for the same member/kind/entity/
 * title, so a daily job never double-sends.
 */

/** Which member notify-pref column gates emails for a notification kind. */
function kind_pref_column(string $kind): ?string
{
    return match ($kind) {
        'issue_reply', 'plan_comment', 'reply_accepted' => 'notify_reply',
        'event_changed', 'event_cancelled', 'event_reminder' => 'notify_event',
        'exam_reminder', 'cert_expiring' => 'notify_exam',
        'digest' => 'notify_digest',
        default => null,   // e.g. 'invite' — always allowed
    };
}

/**
 * Insert a notification unless an identical one already exists (dedup by member/kind/
 * entity/title). Returns the new id, or null if it already existed.
 */
function notify_once(PDO $pdo, int $memberId, string $kind, ?string $entityType, ?int $entityId, string $title, ?string $body = null): ?int
{
    $chk = $pdo->prepare(<<<'SQL'
        SELECT 1 FROM notifications
        WHERE member_id = :m AND kind = :k AND title = :t
          AND entity_type IS NOT DISTINCT FROM :et AND entity_id IS NOT DISTINCT FROM :ei
        LIMIT 1
    SQL);
    $chk->execute(['m' => $memberId, 'k' => $kind, 't' => $title, 'et' => $entityType, 'ei' => $entityId]);
    if ($chk->fetchColumn() !== false) {
        return null;
    }
    $st = $pdo->prepare('INSERT INTO notifications (member_id, kind, entity_type, entity_id, title, body) VALUES (:m, :k, :et, :ei, :t, :b) RETURNING id');
    $st->execute(['m' => $memberId, 'k' => $kind, 'et' => $entityType, 'ei' => $entityId, 't' => $title, 'b' => $body]);
    return (int) $st->fetchColumn();
}

/** Scheduled attempts whose exam is exactly $daysOut away (owner opted into exam mail or not — dedup covers both). */
function unsent_notifications(PDO $pdo, int $limit = 100): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT n.*, m.email, m.display_name, m.notify_reply, m.notify_event, m.notify_exam, m.notify_digest
        FROM notifications n JOIN members m ON m.id = n.member_id
        WHERE n.email_sent_at IS NULL AND m.status = 'active'
          -- Agents are members and have addresses, one of them at example.invalid's cousin
          -- example.com. Mailing one is pointless (its run ended) and MaluMail suppresses an
          -- address after a single bounce, which would cost us a real one.
          AND m.member_kind = 'human'
        ORDER BY n.created_at LIMIT :lim
    SQL);
    $st->bindValue('lim', $limit, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}

function mark_notification_emailed(PDO $pdo, int $id): void
{
    $pdo->prepare('UPDATE notifications SET email_sent_at = now() WHERE id = :id')->execute(['id' => $id]);
}

function unread_notifications(PDO $pdo, int $memberId, int $limit = 10): array
{
    $st = $pdo->prepare('SELECT * FROM notifications WHERE member_id = :m AND read_at IS NULL ORDER BY created_at DESC LIMIT :lim');
    $st->bindValue('m', $memberId, PDO::PARAM_INT);
    $st->bindValue('lim', $limit, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}

function mark_notification_read(PDO $pdo, int $id, int $memberId): bool
{
    $st = $pdo->prepare('UPDATE notifications SET read_at = now() WHERE id = :id AND member_id = :m AND read_at IS NULL');
    $st->execute(['id' => $id, 'm' => $memberId]);
    return $st->rowCount() === 1;
}

function mark_all_notifications_read(PDO $pdo, int $memberId): int
{
    $st = $pdo->prepare('UPDATE notifications SET read_at = now() WHERE member_id = :m AND read_at IS NULL');
    $st->execute(['m' => $memberId]);
    return $st->rowCount();
}
