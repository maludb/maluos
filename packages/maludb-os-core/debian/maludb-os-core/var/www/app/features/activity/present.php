<?php
declare(strict_types=1);

/**
 * Activity trail presenters. Whitelists, mirrored by web/lib/schemas/activity.ts. The trail's
 * before/after payloads are NOT presented: the legacy screen never showed them, and they can
 * carry anything a handler logged.
 */

/** One row of the trail (find_activity()). */
function present_activity_row(array $r): array
{
    return [
        'id' => (int) $r['id'],
        'occurred_at' => json_ts($r['occurred_at'] ?? null),
        'actor_name' => $r['actor_name'] ?? null,
        'actor_member_id' => isset($r['actor_member_id']) ? (int) $r['actor_member_id'] : null,
        'actor_is_agent' => ($r['actor_kind'] ?? '') === 'agent',
        'action' => (string) $r['action'],
        'entity_type' => $r['entity_type'] ?? null,
        'entity_id' => isset($r['entity_id']) ? (int) $r['entity_id'] : null,
        'entity_label' => ($r['entity_label'] ?? null) !== null && $r['entity_label'] !== '' ? (string) $r['entity_label'] : null,
        'source' => (string) ($r['source'] ?? ''),
    ];
}

/** Someone who appears in the trail, for the Who filter (activity_actors()). */
function present_activity_actor(array $a): array
{
    return ['id' => (int) $a['member_id'], 'name' => (string) $a['display_name']];
}
