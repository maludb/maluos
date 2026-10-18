<?php
declare(strict_types=1);

/**
 * Action `system_one_set_mode` — log `agent.system_one_mode`. Gate: super. A system_one agent's mode
 * (db/145): `shadow` records what it would do and sends nothing; `live` starts evaluations, opens alerts
 * and escalates. The change is a new configuration version, activated at once, so the history says who
 * switched it and when.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$refuse = static function (string $m): never { emit_action_status(false, ['errors' => [$m]]); respond_invalid([$m]); };
$memberId = request_integer('agent');
$mode = request_string('mode');
if (!in_array($mode, ['shadow', 'live'], true)) { $refuse('Mode is shadow or live.'); }
$agent = $memberId === null ? null : find_agent($pdo, $memberId);
if ($agent === null) { $refuse('That agent does not exist.'); }
$version = find_agent_version($pdo, (int) ($agent['current_config_version_id'] ?? 0));
if ($version === null) { $refuse('That agent has no active configuration.'); }
$st = $pdo->prepare('SELECT harness FROM model_registry WHERE id = :id');
$st->execute(['id' => (int) $version['model_id']]);
if ($st->fetchColumn() !== 'system_one') { $refuse('Only a system_one agent has a shadow or live mode.'); }

$pdo->beginTransaction();
try {
    $new = create_config_version($pdo, $memberId, [
        'job_description' => (string) $version['job_description'], 'model_id' => (int) $version['model_id'],
        'monthly_budget_amount' => $version['monthly_budget_amount'], 'change_note' => 'Mode: ' . $mode,
        'system_prompt_id' => $version['system_prompt_id'] ?? null, 'system_prompt_version' => $version['system_prompt_version'] ?? null,
        'parameters' => json_decode((string) ($version['harness_config'] ?? '{}'), true) ?: [],
        'runtime' => ['mode' => $mode],
    ], (int) current_member_id());
    $pdo->commit();
} catch (Throwable $e) {
    $pdo->rollBack();
    error_log('system_one mode: ' . $e->getMessage());
    $refuse('The mode could not be changed.');
}
activate_config_version($pdo, (int) $new['config_version_id'], (int) current_member_id());
log_activity($pdo, 'agent.system_one_mode', 'agent', $memberId, ['after' => ['mode' => $mode, 'config_version_id' => (int) $new['config_version_id']]]);
$did = $agent['display_name'] . ' is now ' . ($mode === 'live' ? 'LIVE — it acts on what it finds' : 'in shadow — it records what it would do and sends nothing');
emit_action_status(true, ['did' => $did, 'refresh' => 'agentChanged']);
respond_saved(['did' => $did, 'location' => '/agents/' . $memberId]);
