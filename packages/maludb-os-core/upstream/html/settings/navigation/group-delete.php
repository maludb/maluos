<?php
declare(strict_types=1);

/**
 * Action `nav_group_delete` — remove an EMPTY group; entries are moved out first, never deleted
 * with it. Gate: super. Log `nav_group.delete`.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/navigation/queries.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('group');
if ($id === null || ($group = find_nav_group($pdo, $id)) === null) {
    http_response_code(404);
    exit('Group not found.');
}
if (!delete_nav_group($pdo, $id)) {
    $n = (int) $group['item_count'];
    $why = 'Move its ' . ($n === 1 ? 'one entry' : $n . ' entries') . ' to another group first.';
    emit_action_status(false, ['errors' => [$why]]);
    respond_invalid([$why]);   // no template to carry the words: say them
}

log_activity($pdo, 'nav_group.delete', 'nav_group', $id, ['before' => ['name' => $group['name']]]);
emit_action_status(true, ['did' => 'Removed the group ' . $group['name'], 'refresh' => 'navigationChanged']);
header('HX-Push-Url: /settings/navigation');
