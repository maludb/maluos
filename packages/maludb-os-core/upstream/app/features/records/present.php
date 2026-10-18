<?php
declare(strict_types=1);

/**
 * Presenters for what every record carries — tags and notes. Whitelists, mirrored by
 * web/lib/schemas/records.ts (docs/react-migration-plan.md, "Presenters, never raw rows").
 */

/** One tag on a record (find_taggings()). */
function present_tagging(array $t): array
{
    return ['tag_id' => (int) $t['tag_id'], 'name' => $t['tag_name']];
}

/** One note on a record (find_record_comments()). `mine` decides who is offered Delete. */
function present_record_comment(array $c, int $viewerId): array
{
    return [
        'id' => (int) $c['comment_id'],
        'author_name' => $c['author_name'] ?? null,
        'body' => $c['body'],
        'created_at' => json_ts($c['created_at'] ?? null),
        'mine' => (int) $c['author_member_id'] === $viewerId,
    ];
}

/** A member offered in an owner or manager picker (selectable_members()). Was Contacts', until the kernel cut of 2026-09-22. */
function present_member_option(array $m): array
{
    return ['id' => (int) $m['member_id'], 'name' => $m['display_name'], 'kind' => $m['member_kind']];
}

/** A department offered in a picker (find_departments()). */
function present_department_option(array $d): array
{
    return ['id' => (int) $d['department_id'], 'name' => $d['name']];
}
