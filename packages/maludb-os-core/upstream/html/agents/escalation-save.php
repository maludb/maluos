<?php
declare(strict_types=1);

/**
 * Action `escalation_raise` — log `agent_escalation.create`. Gate: agents only — the one
 * part of an agent's own surface that works before the runtime exists (build spec): an agent
 * with a minted action token can already call the actions server. `open_ticket` is accepted
 * but answered honestly: the tickets module is not built yet, so no ticket is opened.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_agent_caller();
require_post();
verify_csrf();

$pdo = db();
$agentMemberId = (int) current_member_id();
[$fields, $errors] = escalation_fields_from_request();

if ($errors !== []) {
    emit_action_status(false, ['errors' => $errors]);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    http_response_code(422);
    echo '<div class="alert alert-danger m-4">' . implode('<br>', array_map('e', $errors)) . '</div>';
    exit;
}

check_approval($pdo, 'escalation_raise', 'agent_escalation.create', $fields['summary'], $fields);

$escalation = raise_escalation($pdo, $agentMemberId, $fields);
if ($escalation === []) {
    emit_action_status(false, ['errors' => ['The escalation could not be raised.']]);
    http_response_code(500);
    exit('The escalation could not be raised.');
}

log_activity($pdo, 'agent_escalation.create', 'agent_escalation', (int) $escalation['escalation_id'], [
    'after' => ['reason_kind' => $escalation['reason_kind'], 'summary' => $escalation['summary'],
                'to_member_id' => $escalation['to_member_id']],
]);

// The recipient hears of it (2026-09-27): an escalation nobody is told about is a note in a drawer —
// the Auditor's and the Sysadmin's alerts arrive this way. In-app now; the mail cron sends it on.
require_once dirname(__DIR__, 2) . '/app/features/notifications/queries.php';
// A person with a personal assistant hears from agents only through it (db/154-155): the escalation lands
// in the assistant's inbox as `decision_needed`, urgent, and the assistant tells its person. The
// escalation row still names the person — the decision stays theirs. A system delivery, so the tree rule
// of message_send does not apply (any agent may escalate to a person).
$assistant = null;
if (!empty($escalation['to_member_id'])) {
    $st = $pdo->prepare("SELECT p.member_id FROM agent_profiles p JOIN members m ON m.id = p.member_id
                          WHERE p.principal_member_id = :person AND p.status = 'active' AND m.status = 'active'
                            AND p.member_id <> :me");
    $st->execute(['person' => (int) $escalation['to_member_id'], 'me' => $agentMemberId]);
    $assistant = $st->fetchColumn() ?: null;
}
if ($assistant !== null) {
    try {
        $pdo->beginTransaction();
        $st = $pdo->prepare('INSERT INTO agent_message_threads (subject, principal_member_id, opened_by) VALUES (:s, :p, :by) RETURNING id');
        $st->execute(['s' => mb_substr('Escalation: ' . (string) $escalation['summary'], 0, 300), 'p' => (int) $escalation['to_member_id'], 'by' => $agentMemberId]);
        $threadId = (int) $st->fetchColumn();
        $pdo->prepare("INSERT INTO agent_messages (thread_id, from_member_id, to_member_id, kind, priority, subject, body, related_entity_type,
                              related_entity_id, sent_run_id)
                       VALUES (:t, :f, :to, 'decision_needed', 'urgent', :s, :b, 'agent_escalation', :e, :run)")
            ->execute(['t' => $threadId, 'f' => $agentMemberId, 'to' => (int) $assistant,
                       's' => mb_substr((string) $escalation['summary'], 0, 300),
                       'b' => 'An escalation for your person (' . $escalation['reason_kind'] . '): ' . $escalation['summary']
                           . "\n\nThe decision is theirs — tell them plainly and say what it needs from them.",
                       'e' => (int) $escalation['escalation_id'], 'run' => current_agent_run_id()]);
        $pdo->prepare('UPDATE agent_message_threads SET hop_count = 1 WHERE id = :t')->execute(['t' => $threadId]);
        $pdo->commit();
    } catch (Throwable $e) {
        $pdo->rollBack();
        error_log('escalation to assistant failed: ' . $e->getMessage());
        $assistant = null;                                     // fall back to telling the person directly
    }
}
if (!empty($escalation['to_member_id']) && $assistant === null) {
    try {
        notify_once($pdo, (int) $escalation['to_member_id'], 'agent_escalation', 'agent_escalation', (int) $escalation['escalation_id'],
            'Escalation from ' . (current_member()['display_name'] ?? 'an agent') . ': ' . mb_substr((string) $escalation['summary'], 0, 150),
            (string) $escalation['summary']);
    } catch (Throwable $e) {
        error_log('escalation notify failed: ' . $e->getMessage());   // the escalation itself stands
    }
}
$did = 'Raised an escalation: ' . $escalation['summary'];
if (!empty($fields['open_ticket'])) {
    $did .= ' (a ticket was not opened — the tickets module is not built yet)';
}
emit_action_status(true, ['did' => $did, 'refresh' => 'escalationChanged']);
hx_trigger('escalationChanged');
render_escalations_page($pdo);
