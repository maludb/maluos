<?php
declare(strict_types=1);

/**
 * Action `nav_item_save` — add an entry to the menu, or change one. Every entry: its name, icon,
 * group and status. A LINK (an entry added here, belonging to no application) and an external
 * application's entry also take their address and whether it opens in this tab or a new one; a
 * built-in application's address is the application's own and stays. The key is never editable
 * (DOM ids, smokes). Without `item`, this adds. Gate: super. Log `nav_item.save`.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/navigation/queries.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$id = request_integer('item');
$item = null;
if ($id !== null && ($item = find_nav_item($pdo, $id)) === null) {
    http_response_code(404);
    exit('Menu entry not found.');
}
$label = request_string('label');
$icon = request_string('icon', 'feather-link');
$groupId = request_integer('group');
$status = request_string('status', $item['status'] ?? 'active');
$addressEditable = $item === null || nav_item_address_editable($item);
$url = $addressEditable ? request_string('url', $item['url'] ?? '') : $item['url'];
$opens = $addressEditable ? request_string('opens', $item['opens'] ?? 'same') : $item['opens'];

$errors = [];
if ($label === '' || mb_strlen($label) > 40) {
    $errors[] = 'An entry needs a name (up to 40 characters).';
}
if (preg_match('/^feather-[a-z0-9-]{1,40}$/', $icon) !== 1) {
    $errors[] = 'The icon is a Feather icon name, like feather-briefcase.';
}
if ($groupId === null || find_nav_group($pdo, $groupId) === null) {
    $errors[] = 'Choose the group it sits in.';
}
if ($addressEditable && ($why = nav_url_problem($url)) !== null) {
    $errors[] = $why;
}
if (!in_array($opens, ['same', 'new_tab'], true)) {
    $errors[] = 'An entry opens in this tab or in a new tab.';
}
$allowed = $item === null ? ['active', 'hidden'] : nav_item_allowed_statuses($item);
if (!in_array($status, $allowed, true)) {
    $errors[] = match (true) {
        $item !== null && (bool) $item['is_locked'] => $item['label'] . ' is always active — it is how people find their way back.',
        $item === null || nav_item_is_link($item)   => 'A link can be active or hidden — there is nothing of its own to switch off.',
        default => $item['label'] . ' can be active or hidden. It is part of the platform itself, so there is nothing to switch off.',
    };
}
if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);   // no template to carry the words: say them
}

if ($item === null) {
    $saved = insert_nav_item($pdo, (int) $groupId, $label, $icon, $url, $opens, $status, (int) current_member_id());
    log_activity($pdo, 'nav_item.save', 'nav_item', (int) $saved['id'], [
        'after' => ['key' => $saved['item_key'], 'label' => $saved['label'], 'icon' => $saved['icon'], 'group_id' => (int) $saved['group_id'],
                    'status' => $saved['status'], 'url' => $saved['url'], 'opens' => $saved['opens']],
    ]);
    emit_action_status(true, ['did' => 'Added ' . $saved['label'] . ' to the menu', 'record_id' => (int) $saved['id'], 'refresh' => 'navigationChanged']);
    header('HX-Push-Url: /settings/navigation');
    exit;
}

$saved = update_nav_item($pdo, $id, $label, $icon, (int) $groupId, $status, $url, $opens);
log_activity($pdo, 'nav_item.save', 'nav_item', $id, [
    'before' => ['label' => $item['label'], 'icon' => $item['icon'], 'group_id' => (int) $item['group_id'], 'status' => $item['status'],
                 'url' => $item['url'], 'opens' => $item['opens']],
    'after'  => ['label' => $saved['label'], 'icon' => $saved['icon'], 'group_id' => (int) $saved['group_id'], 'status' => $saved['status'],
                 'url' => $saved['url'], 'opens' => $saved['opens']],
]);
emit_action_status(true, ['did' => 'Saved ' . $saved['label'], 'record_id' => $id, 'refresh' => 'navigationChanged']);
header('HX-Push-Url: /settings/navigation');
