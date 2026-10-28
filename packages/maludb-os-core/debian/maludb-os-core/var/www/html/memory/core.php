<?php
declare(strict_types=1);

/**
 * Core memory of one member — the standing facts kept for an agent or a person. JSON only
 * (React). Read rule = the Memory MCP server's core_memory tool; `can.set` = the write handler's
 * own rule (memory_can_set_core), so the form appears exactly when core-set.php would accept.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/memory/maludb.php';
require_once dirname(__DIR__, 2) . '/app/features/memory/scope.php';
require_once dirname(__DIR__, 2) . '/app/features/memory/reads.php';
require_once dirname(__DIR__, 2) . '/app/features/memory/present.php';

require_insider();
$pdo = db();

$memberId = request_integer('member') ?? (int) current_member_id();
[$allowed, $member] = memory_may_read_core($pdo, $memberId);
if ($member === null) {
    http_response_code(404);
    exit('Member not found.');
}
if (!$allowed) {
    deny('You may read your own core memory, or that of an agent you manage.');
}

[$profile, $unavailable] = memory_profile(memory_principal_ref($memberId, (string) $member['member_kind']));
$entries = [];
foreach (is_array($profile['entries'] ?? null) ? $profile['entries'] : [] as $key => $entry) {
    if (is_array($entry)) {
        $entries[] = present_core_entry((string) $key, $entry);
    }
}
usort($entries, static fn (array $a, array $b): int => strcmp($a['key'], $b['key']));

log_screen_view($pdo, 'memory-core');
respond_screen([
    'member' => [
        'member_id' => $memberId,
        'name' => (string) $member['display_name'],
        'is_agent' => $member['member_kind'] === 'agent',
        'is_me' => $memberId === (int) current_member_id(),
    ],
    'entries' => $entries,
    'memory_available' => $unavailable === null,
    'memory_error' => $unavailable,
    'can' => ['set' => memory_can_set_core($pdo, $memberId)],
]);
