<?php
declare(strict_types=1);

/**
 * Action `memory_remember` — add something to shared memory on MaluDB.
 * Scope is resolved HERE from the signed-in member (features/memory/scope.php); nobody names a
 * namespace. A private memory is free. What goes into a department's or the organisation's memory
 * is read by every colleague's next run as something the business knows, so an AGENT's shared
 * write pauses for a person (policy "Agents: writing shared memory", event memory.remember_shared).
 * The log keeps an excerpt and the MaluDB document id; the memory itself lives in MaluDB.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/memory/maludb.php';
require_once dirname(__DIR__, 2) . '/app/features/memory/scope.php';

require_post();
verify_csrf();
require_insider();

$pdo = db();
$text = trim(request_string('text'));
// `subject` is the parameter; `subjects` was what the manifest named until 2026-09-19 (an agent was
// refused seven times for sending it) and is still read, first entry only, so an old caller works.
$subject = trim(request_string('subject'));
if ($subject === '') {
    $given = $_POST['subjects'] ?? '';
    $subject = trim(is_array($given) ? (string) (array_values($given)[0] ?? '') : (string) $given);
}
$scope = request_string('scope') ?: 'self';
$errors = [];
if ($text === '') {
    $errors[] = 'Say what should be remembered.';
} elseif (strlen($text) > MEMORY_TEXT_MAX) {
    $errors[] = 'That is too long to remember in one piece.';
}
if ($subject === '') {
    $errors[] = 'Say what it is about (a customer, a vendor, a process) — memory is filed and found by subject.';
} elseif (strlen($subject) > MEMORY_SUBJECT_MAX) {
    $errors[] = 'The subject is too long.';
}
[$namespace, $scopeError, $departmentId] = memory_write_namespace($pdo, $scope, request_integer('department'));
if ($scopeError !== null) {
    $errors[] = $scopeError;
}
if ($errors !== []) {
    memory_fail($errors);
}

$shared = $scope !== 'self';
$event = $shared ? 'memory.remember_shared' : 'memory.remember';
$excerpt = mb_substr($text, 0, 200);
if ($shared) {
    check_approval($pdo, 'memory_remember', $event,
        'Add to ' . ($scope === 'org' ? 'the organisation\'s' : 'a department\'s') . ' memory, about ' . $subject . ': "' . $excerpt . '"',
        ['scope' => $scope, 'department' => $departmentId, 'subject' => $subject, 'text' => $excerpt], 'memory', null);
}

[$documentId, $error] = maludb_remember($namespace, $subject, $text, [
    'member_id' => (int) current_member_id(), 'scope' => $scope,
    'agent_run_id' => function_exists('current_agent_run_id') ? current_agent_run_id() : null,
]);
if ($error !== null) {
    memory_fail([$error], 424);
}

log_activity($pdo, $event, 'memory', $documentId, [
    'after' => ['scope' => $scope, 'namespace' => $namespace, 'subject' => $subject, 'excerpt' => $excerpt],
]);
emit_action_status(true, ['did' => 'Remembered, about ' . $subject . ($shared ? ' (' . $scope . ' memory)' : ''),
    'document_id' => $documentId, 'scope' => $scope]);
