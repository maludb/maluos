<?php
declare(strict_types=1);

/**
 * Screen `navigation-settings` — /settings/navigation: the whole menu as the super-admin arranges
 * it — every group and entry, whatever its status (docs/build-specs/data-driven-nav.md, step 3).
 * `?item=<id>` answers one entry, for its edit page; `?new=1` the blank for the add page (with
 * `&group=<id>` preselected). Gate: super. JSON only — born after the React cut-over, no template.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/navigation/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/navigation/present.php';

require_super_admin();

$pdo = db();
$groups = find_nav_groups($pdo);
$groupOptions = array_map(static fn (array $g): array => ['id' => (int) $g['id'], 'name' => $g['name']], $groups);

$itemId = request_integer('item');
if ($itemId !== null) {
    $item = find_nav_item($pdo, $itemId);
    if ($item === null) {
        http_response_code(404);
        exit('Menu entry not found.');
    }
    log_screen_view($pdo, 'navigation-item');
    respond_screen(['item' => present_nav_item($item), 'options' => ['groups' => $groupOptions]]);
}

if (request_bool('new')) {
    log_screen_view($pdo, 'navigation-item-add');
    respond_screen(['item' => null, 'group_id' => request_integer('group'), 'options' => ['groups' => $groupOptions]]);
}

log_screen_view($pdo, 'navigation-settings');
respond_screen(['groups' => array_map('present_nav_group', $groups), 'options' => ['groups' => $groupOptions]]);
