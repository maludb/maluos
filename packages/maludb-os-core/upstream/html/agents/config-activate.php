<?php
declare(strict_types=1);

/**
 * Action `agent_activate_version` — log `agent_config_version.activate` (carrying whether it
 * was evaluated). Gate: mod:hr, agent's manager (OR). Evals advise and never block (owner,
 * 2026-09-20): a version with a passing run for it records that run; any other version goes
 * live too, and both the screen and the log say it went live unevaluated — naming the eval
 * set when one exists.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
$versionId = request_integer('version');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}
agent_require_hr_or_manager($pdo, $agent);
agent_refuse_agent_caller();

if ($versionId === null || ($version = find_agent_version($pdo, $versionId)) === null
        || (int) $version['agent_member_id'] !== $id) {
    render_agent_page($pdo, $id, 'job', ['That configuration version does not belong to this agent.']);
}

// A version may name a different model from the one the agent was hired on, so the harness is
// checked again here: going live on a model nothing can run is the same defect as hiring onto one.
if (($harnessProblem = agent_harness_error(find_model($pdo, (int) $version['model_id']))) !== null) {
    render_agent_page($pdo, $id, 'job', [$harnessProblem]);
}

check_approval($pdo, 'agent_activate_version', 'agent_config_version.activate',
    'Activate version ' . $version['version_no'] . ' for ' . $agent['display_name'],
    ['agent' => $id, 'version' => $versionId], 'member', $id);

try {
    $result = activate_config_version($pdo, $versionId, (int) current_member_id());
} catch (RuntimeException $ex) {
    render_agent_page($pdo, $id, 'job', [$ex->getMessage()]);
}

$did = $result['gated']
    ? 'Activated version ' . $version['version_no'] . ' for ' . $agent['display_name']
        . ' (passed eval set "' . $result['eval_set_name'] . '")'
    : 'Activated version ' . $version['version_no'] . ' for ' . $agent['display_name']
        . ($result['eval_set_name'] !== null
            ? ' — not evaluated: eval set "' . $result['eval_set_name'] . '" has no passing run for this version'
            : ' without an eval — no eval set exists for this agent yet');

log_activity($pdo, 'agent_config_version.activate', 'member', $id, [
    'after' => ['version_no' => $version['version_no'], 'gated' => $result['gated'],
                'eval_set' => $result['eval_set_name']],
]);
emit_action_status(true, ['did' => $did, 'gated' => $result['gated'], 'refresh' => 'agentChanged']);
hx_trigger('agentChanged');
render_agent_page($pdo, $id, 'job');
