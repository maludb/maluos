<?php
declare(strict_types=1);

/**
 * Presenters for the focused Agent View (docs/build-specs/agent-view-focus-graph.md).
 * Whitelists, mirrored by web/lib/focus-graph.ts — named keys only, ids as ints, money as
 * money() strings (docs/react-migration-plan.md, "Presenters, never raw rows").
 *
 * A node is what the focus record's own screen prints about that row, reduced to a name, one
 * line under it (`title`) and the React path of its day-to-day screen (`href`). Nothing else
 * about the row leaves: no email, no amount as a number, no constraint, no instruction text.
 */

const FOCUS_GROUP_CAP = 40;    // level-2 nodes per ring
const FOCUS_GRAPH_CAP = 200;   // nodes per graph, centre and rings included

/**
 * The React path of a record's day-to-day screen — computed here, the one place that knows
 * the canonical URLs. NULL for a row that has no screen of its own (a tool grant, a duty).
 */
function focus_href(string $type, int $id, array $context = []): ?string
{
    return match ($type) {
        'member'       => (($context['member_kind'] ?? 'human') === 'agent' ? '/agents/' : '/team/') . $id,
        'department'   => '/team/departments/' . $id,
        // A milestone has a form but no page: it is read on its project's Milestones tab.
        'location'     => '/locations/' . $id,
        'application'  => '/applications/' . $id,
        default        => null,
    };
}

/** The centre: the focus record itself, at level 0. */
function present_focus_centre(string $type, int $id, string $name, ?string $title, array $extra = []): array
{
    return [
        'id'        => $type . ':' . $id,
        'type'      => $type,
        'level'     => 0,
        'name'      => $name,
        'title'     => $title !== null && $title !== '' ? $title : null,
        'href'      => focus_href($type, $id, $extra),
        'is_centre' => true,
    ] + present_focus_member_extra($extra);
}

/** One ring. member_count is the true count; truncated says the ring shows fewer. */
function present_focus_group(string $key, string $name, int $memberCount, bool $truncated): array
{
    return [
        'id'           => 'group:' . $key,
        'type'         => 'group',
        'level'        => 1,
        'name'         => $name,
        'member_count' => $memberCount,
        'truncated'    => $truncated,
    ];
}

/** One record on a ring. */
function present_focus_node(string $type, int $id, string $name, ?string $title, array $context = []): array
{
    return [
        'id'    => $type . ':' . $id,
        'type'  => $type,
        'level' => 2,
        'name'  => $name,
        'title' => $title !== null && $title !== '' ? $title : null,
        'href'  => focus_href($type, $id, $context),
    ] + present_focus_member_extra($context);
}

/** What only a member node carries: whether it is a person or an agent, and its picture. */
function present_focus_member_extra(array $context): array
{
    if (!isset($context['member_kind'])) {
        return [];
    }
    return [
        'member_kind' => (string) $context['member_kind'],
        'avatar_url'  => ($context['avatar_url'] ?? '') !== '' ? (string) $context['avatar_url'] : null,
    ];
}
