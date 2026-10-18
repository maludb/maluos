<?php
declare(strict_types=1);

/**
 * Action `nav_item_delete` — remove a link, or an external application's entry, from the menu.
 * A built-in application's entry is never deleted: hide it, and it is there to bring back. A
 * locked entry stays. Gate: super. Log `nav_item.delete`.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/navigation/queries.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('item');
if ($id === null || ($item = find_nav_item($pdo, $id)) === null) {
    http_response_code(404);
    exit('Menu entry not found.');
}
if (!nav_item_deletable($item)) {
    $why = $item['is_locked']
        ? $item['label'] . ' is always in the menu — it is how people find their way back.'
        : $item['label'] . ' is part of the platform: hide it instead, and it is there to bring back.';
    emit_action_status(false, ['errors' => [$why]]);
    respond_invalid([$why]);   // no template to carry the words: say them
}

delete_nav_item($pdo, $id);
log_activity($pdo, 'nav_item.delete', 'nav_item', $id, [
    'before' => ['key' => $item['item_key'], 'label' => $item['label'], 'group_id' => (int) $item['group_id'], 'status' => $item['status'],
                 'url' => $item['url'], 'opens' => $item['opens'], 'application_id' => $item['application_id'] === null ? null : (int) $item['application_id']],
]);
emit_action_status(true, ['did' => 'Removed ' . $item['label'] . ' from the menu', 'refresh' => 'navigationChanged']);
header('HX-Push-Url: /settings/navigation');
