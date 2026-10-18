<?php
declare(strict_types=1);

/** Whitelist presenters for Settings → Navigation. Requires navigation/queries.php. */

function present_nav_item(array $i): array
{
    $allowed = nav_item_allowed_statuses($i);
    return [
        'id' => (int) $i['id'],
        'key' => $i['item_key'],
        'group_id' => (int) $i['group_id'],
        'label' => $i['label'],
        'icon' => $i['icon'],
        'url' => $i['url'],
        'opens' => $i['opens'],
        'module' => $i['module'],
        'audience' => $i['audience'],
        'status' => $i['status'],
        'status_label' => NAV_STATUS_LABELS[$i['status']] ?? $i['status'],
        'is_locked' => (bool) $i['is_locked'],
        'is_builtin' => (bool) $i['is_builtin'],
        'is_link' => nav_item_is_link($i),
        'address_editable' => nav_item_address_editable($i),
        'deletable' => nav_item_deletable($i),
        'application_name' => $i['application_name'],
        'application_id' => isset($i['application_id']) ? (int) $i['application_id'] : null,
        'allowed_statuses' => array_map(
            static fn (string $s): array => ['id' => $s, 'name' => NAV_STATUS_LABELS[$s]], $allowed),
        'siblings' => array_map(
            static fn (array $s): array => ['label' => (string) $s['label'], 'status' => (string) $s['status']],
            json_decode((string) $i['siblings'], true) ?: []),
    ];
}

function present_nav_group(array $g): array
{
    return [
        'id' => (int) $g['id'],
        'name' => $g['name'],
        'items' => array_map('present_nav_item', $g['items'] ?? []),
    ];
}
