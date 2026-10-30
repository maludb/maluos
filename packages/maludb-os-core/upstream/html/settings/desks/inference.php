<?php
declare(strict_types=1);

/**
 * Settings → Desks → "Shared inference" (db/191): an operator flips the `scheduler` entitlement (until Phase 9's
 * contracts service sets it), adds a policy rule, or removes one. `op` = scheduler (on=1|0) | rule_add (subject,
 * backend_location_id, allow, max_class, max_classification, priority, note) | rule_delete (id). Gate: super-admin.
 * Every change bumps the versions, so every member's next heartbeat says inference_changed / peers_changed.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/settings/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/estate/nodes.php';
require_login(); require_post(); verify_csrf();
$pdo = db(); $me = (int) current_member_id();
$m = find_member_by_id($pdo, $me);
if (!estate_operator($m)) {
    emit_action_status(false, ['errors' => ['Only an operator (super-admin) changes the estate\'s inference policy.']]);
    respond_invalid(['Only an operator (super-admin) changes the estate\'s inference policy.']);
}
$op = request_string('op');
$did = '';
try {
    $pdo->beginTransaction();
    if ($op === 'scheduler') {
        $on = request_string('on') === '1';
        inference_set_scheduler($pdo, $on);
        log_activity($pdo, 'estate.inference.scheduler', null, null, ['after' => ['scheduler' => $on]]);
        $did = $on ? 'The scheduler entitlement is on' : 'The scheduler entitlement is off';
    } elseif ($op === 'rule_add') {
        $r = inference_rule_add($pdo, ['subject' => request_string('subject', 'org'), 'backend_location_id' => request_integer('backend_location_id'),
                                       'allow' => request_string('allow', '1') === '1', 'max_class' => request_string('max_class'), 'max_classification' => request_string('max_classification'),
                                       'priority' => request_integer('priority') ?? 0, 'note' => request_string('note')], $me);
        log_activity($pdo, 'estate.inference.rule.add', 'estate_inference_policy', (int) $r['id'], ['after' => present_inference_rule($r)]);
        $did = 'Rule added';
    } elseif ($op === 'rule_delete') {
        $id = request_integer('id') ?? 0;
        if (!inference_rule_delete($pdo, $id)) { throw new InvalidArgumentException('No such rule.'); }
        log_activity($pdo, 'estate.inference.rule.delete', 'estate_inference_policy', $id, []);
        $did = 'Rule removed';
    } else {
        throw new InvalidArgumentException('op is scheduler, rule_add or rule_delete.');
    }
    $pdo->commit();
} catch (InvalidArgumentException $ex) {
    if ($pdo->inTransaction()) { $pdo->rollBack(); }
    emit_action_status(false, ['errors' => [$ex->getMessage()]]);
    respond_invalid([$ex->getMessage()]);
}
emit_action_status(true, ['did' => $did]);
if (wants_json()) {
    respond_saved(['did' => $did]);
}
echo settings_section_html($pdo, $me, 'desks');
