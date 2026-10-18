<?php
declare(strict_types=1);

/**
 * Action `nav_group_save` — add a heading, or rename one. One group may have no name: its
 * entries sit at the top with no heading. Gate: super. Log `nav_group.save`.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/navigation/queries.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('group');
$name = request_string('name');
$before = null;
if ($id !== null && ($before = find_nav_group($pdo, $id)) === null) {
    http_response_code(404);
    exit('Group not found.');
}
$errors = [];
if (mb_strlen($name) > 40) {
    $errors[] = 'Keep a heading under 40 characters.';
}
if ($id === null && $name === '') {
    $errors[] = 'A new group needs a heading.';
}
if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);   // no template to carry the words: say them
}

try {
    $group = upsert_nav_group($pdo, $id, $name);
} catch (PDOException $ex) {
    if ($ex->getCode() !== '23505') {
        throw $ex;
    }
    $why = $name === '' ? 'Only one group can go without a heading.' : 'There is already a group called ' . $name . '.';
    emit_action_status(false, ['errors' => [$why]]);
    respond_invalid([$why]);
}

log_activity($pdo, 'nav_group.save', 'nav_group', (int) $group['id'], [
    'before' => $before !== null ? ['name' => $before['name']] : null,
    'after'  => ['name' => $group['name']],
]);
emit_action_status(true, ['did' => 'Saved the group ' . ($group['name'] ?: '(no heading)'), 'record_id' => (int) $group['id'], 'refresh' => 'navigationChanged']);
header('HX-Push-Url: /settings/navigation');
