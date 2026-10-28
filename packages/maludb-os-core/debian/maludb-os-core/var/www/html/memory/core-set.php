<?php
declare(strict_types=1);

/**
 * Action `core_memory_set` — set one entry of a member's standing memory (MaluDB principal
 * profile). An update SUPERSEDES the old value and the history stays readable. Gate: the member
 * itself, whoever administers them, or an agent's nearest human manager.
 * An agent's core memory is rendered into its own system prompt on every run, so an AGENT changing
 * its own pauses for a person (policy "Agents: changing their own core memory").
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/memory/maludb.php';
require_once dirname(__DIR__, 2) . '/app/features/memory/scope.php';

require_post();
verify_csrf();
require_insider();

$pdo = db();
$memberId = request_integer('member') ?? (int) current_member_id();
$key = trim(request_string('key'));
$value = trim(request_string('value'));
$kind = memory_member_kind($pdo, $memberId);
if ($kind === null) {
    memory_fail(['That member does not exist.'], 404);
}
if (!memory_can_set_core($pdo, $memberId)) {
    deny('You can change your own core memory, or that of someone you administer.');
}
$errors = [];
if (!preg_match(MEMORY_KEY_PATTERN, $key)) {
    $errors[] = 'The key may hold letters, digits and _ . - (for example vendor_naming).';
}
if ($value === '') {
    $errors[] = 'Say what should be kept.';
} elseif (strlen($value) > 4000) {
    $errors[] = 'Core memory is for short standing facts — that is too long.';
}
if ($errors !== []) {
    memory_fail($errors);
}

check_approval($pdo, 'core_memory_set', 'memory.core_set',
    'Change core memory "' . $key . '": "' . mb_substr($value, 0, 200) . '"',
    ['member' => $memberId, 'key' => $key, 'value' => mb_substr($value, 0, 200)], 'member', $memberId);

[$entry, $error] = maludb_profile_set(memory_principal_ref($memberId, $kind), $key, $value, null);
if ($error !== null) {
    memory_fail([$error], 424);
}
log_activity($pdo, 'memory.core_set', 'member', $memberId, [
    'after' => ['key' => $key, 'excerpt' => mb_substr($value, 0, 200), 'supersedes' => $entry['supersedes'] ?? null],
]);
emit_action_status(true, ['did' => 'Core memory "' . $key . '" set', 'key' => $key]);
