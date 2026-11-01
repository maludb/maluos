<?php
declare(strict_types=1);

/**
 * Settings → Desks → "Shared memory" (db/192): an operator adds a policy rule or removes one. `op` = rule_add (subject,
 * scope, holder_location_id, allow, max_classification, replicate, priority, note) | rule_delete (id) | limits (fanout_max,
 * rate_per_min). Gate: super-admin. Every change bumps the versions, so every member's next heartbeat says
 * memory_changed / memory_peers_changed.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/settings/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/estate/nodes.php';
require_login(); require_post(); verify_csrf();
$pdo = db(); $me = (int) current_member_id();
$m = find_member_by_id($pdo, $me);
if (!estate_operator($m)) {
    emit_action_status(false, ['errors' => ['Only an operator (super-admin) changes the estate\'s memory policy.']]);
    respond_invalid(['Only an operator (super-admin) changes the estate\'s memory policy.']);
}
$op = request_string('op');
$did = '';
try {
    $pdo->beginTransaction();
    if ($op === 'rule_add') {
        $r = memory_rule_add($pdo, ['subject' => request_string('subject', 'org'), 'scope' => request_string('scope', '*'), 'holder_location_id' => request_integer('holder_location_id'),
                                    'allow' => request_string('allow', '1') === '1', 'max_classification' => request_string('max_classification'),
                                    'replicate' => request_string('replicate') === '1', 'priority' => request_integer('priority') ?? 0, 'note' => request_string('note')], $me);
        log_activity($pdo, 'estate.memory.rule.add', 'estate_memory_policy', (int) $r['id'], ['after' => present_memory_rule($r)]);
        $did = 'Rule added';
    } elseif ($op === 'rule_delete') {
        $id = request_integer('id') ?? 0;
        if (!memory_rule_delete($pdo, $id)) { throw new InvalidArgumentException('No such rule.'); }
        log_activity($pdo, 'estate.memory.rule.delete', 'estate_memory_policy', $id, []);
        $did = 'Rule removed';
    } elseif ($op === 'limits') {
        $fan = request_integer('fanout_max') ?? 8; $rate = request_integer('rate_per_min') ?? 30;
        if ($fan < 1 || $fan > 32 || $rate < 1 || $rate > 1000) { throw new InvalidArgumentException('fanout_max is 1 to 32, rate_per_min 1 to 1000.'); }
        $pdo->prepare('UPDATE estate_memory_settings SET fanout_max = :f, rate_per_min = :r, updated_at = now() WHERE id = 1')->execute(['f' => $fan, 'r' => $rate]);
        memory_bump($pdo, 'holders');
        log_activity($pdo, 'estate.memory.limits', null, null, ['after' => ['fanout_max' => $fan, 'rate_per_min' => $rate]]);
        $did = 'Limits saved';
    } else {
        throw new InvalidArgumentException('op is rule_add, rule_delete or limits.');
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
