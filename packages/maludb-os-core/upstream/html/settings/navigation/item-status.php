<?php
declare(strict_types=1);

/**
 * Action `nav_item_set_status` — active (in the sidebar), hidden (usable, no sidebar entry) or
 * disabled (closed to people, agents and MCP; data untouched). Gate: super. Log `nav_item.status`.
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
$status = request_string('status');
if (!in_array($status, NAV_STATUSES, true)) {
    emit_action_status(false, ['errors' => ['A status is active, hidden or disabled.']]);
    respond_invalid(['A status is active, hidden or disabled.']);   // no template to carry the words: say them
}
if (!in_array($status, nav_item_allowed_statuses($item), true)) {
    $why = $item['is_locked']
        ? $item['label'] . ' is always active — it is how people find their way back.'
        : $item['label'] . ' can be active or hidden. It is part of the platform itself, so there is nothing to switch off.';
    emit_action_status(false, ['errors' => [$why]]);
    respond_invalid([$why]);
}

set_nav_item_status($pdo, $id, $status);
log_activity($pdo, 'nav_item.status', 'nav_item', $id, [
    'before' => ['status' => $item['status']],
    'after'  => ['status' => $status, 'label' => $item['label'], 'module' => $item['module']],
]);
emit_action_status(true, ['did' => $item['label'] . ' is now ' . $status, 'record_id' => $id, 'refresh' => 'navigationChanged']);
header('HX-Push-Url: /settings/navigation');
