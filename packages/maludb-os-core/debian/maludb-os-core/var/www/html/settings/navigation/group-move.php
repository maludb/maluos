<?php
declare(strict_types=1);

/**
 * Action `nav_group_move` — one place up or down. Gate: super. Log `nav_group.move`.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/navigation/queries.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('group');
$direction = request_string('direction');
if ($id === null || ($row = find_nav_group($pdo, $id)) === null) {
    http_response_code(404);
    exit('Not found.');
}
if (!in_array($direction, ['up', 'down'], true)) {
    emit_action_status(false, ['errors' => ['Move it up or down.']]);
    respond_invalid(['Move it up or down.']);   // no template to carry the words: say them
}
if (!move_nav_row($pdo, 'nav_groups', $id, $direction)) {
    emit_action_status(false, ['errors' => ['It is already at that end.']]);
    respond_invalid(['It is already at that end.']);
}

log_activity($pdo, 'nav_group.move', 'nav_group', $id, ['after' => ['direction' => $direction]]);
emit_action_status(true, ['did' => 'Moved ' . ($row['name'] ?: 'the top group') . ' ' . $direction, 'record_id' => $id, 'refresh' => 'navigationChanged']);
header('HX-Push-Url: /settings/navigation');
