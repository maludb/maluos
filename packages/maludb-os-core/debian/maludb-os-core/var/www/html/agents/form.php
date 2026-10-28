<?php
declare(strict_types=1);

/**
 * Hire / edit form (screens `agent-hire` / `agent-edit`). Gate: require_module_grant('hr') —
 * the spec states the FORMS themselves are mod:hr only; the write endpoint for an edit
 * (config-save.php) additionally admits the agent's own manager, which is why a manager with
 * no hr grant can still act through voice/the action channel even though this screen refuses
 * them. Agents never reach this (agent_refuse_agent_caller()).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';

require_module_grant('hr');
agent_refuse_agent_caller();
agents_require_files();

$pdo = db();
$id = request_integer('id');
$models = find_models($pdo, false);

if ($id !== null) {
    $agent = find_agent($pdo, $id);
    if ($agent === null) {
        http_response_code(404);
        exit('Agent not found.');
    }
    $version = current_or_latest_agent_version($pdo, $agent);
    log_screen_view($pdo, 'agent-edit');
    if (wants_json()) {
        require_once dirname(__DIR__, 2) . '/app/features/agents/present.php';
        respond_screen([
            'agent' => present_agent($agent),
            'version' => present_agent_version_form($version),
            'duties' => array_map('present_agent_duty', find_agent_duties($pdo, $id)),
            'options' => [
                'models' => array_map('present_model_option', $models),
                'prompts' => array_map('present_prompt_option', find_active_system_prompt_options($pdo)),
                'kinds' => AGENT_KIND_LABELS,
                'departments' => [], 'managers' => [], 'locations' => [], 'subagents' => [], 'tool_endpoints' => [],
            ],
            'blank_rows' => ['duties' => AGENT_DUTY_BLANK_ROWS, 'tools' => 0],
        ]);
    }
    render_screen('Edit · ' . ($agent['display_name'] ?? 'Agent') . ' · ' . business_name($pdo),
        view('agents/agent-form.php', [
            'isEdit' => true,
            'agent' => $agent,
            'version' => $version,
            'duties' => find_agent_duties($pdo, $id),
            'models' => $models,
            'departments' => [],
            'managerOptions' => [],
            'locationOptions' => [],
            'promptOptions' => find_active_system_prompt_options($pdo),
            'errors' => [],
        ]),
        ['activeNav' => 'nav-agents', 'screen' => 'agent-edit', 'entity' => 'member', 'recordId' => (string) $id]);
}

log_screen_view($pdo, 'agent-hire');
if (wants_json()) {
    require_once dirname(__DIR__, 2) . '/app/features/agents/present.php';
    require_once dirname(__DIR__, 2) . '/app/features/records/present.php';
    respond_screen([
        'agent' => present_agent(['department_id' => request_integer('department_id'),
                                  'job_title' => request_string('job_title')]),
        'version' => null,
        'duties' => [],
        'options' => [
            'models' => array_map('present_model_option', $models),
            'prompts' => array_map('present_prompt_option', find_active_system_prompt_options($pdo)),
            'kinds' => AGENT_KIND_LABELS,
            'departments' => array_map('present_department_option', find_departments($pdo)),
            'managers' => array_map('present_manager_option', find_manager_options($pdo)),
            'locations' => array_map('present_home_location_option', find_home_location_options($pdo)),
            'subagents' => array_map('present_agent_option', find_subagent_options($pdo)),
            'tool_endpoints' => array_map('present_tool_endpoint_option', find_grantable_tool_endpoints($pdo)),
        ],
        'blank_rows' => ['duties' => AGENT_DUTY_BLANK_ROWS, 'tools' => AGENT_TOOL_BLANK_ROWS],
    ]);
}
render_screen('Hire an agent · ' . business_name($pdo),
    view('agents/agent-form.php', [
        'isEdit' => false,
        'agent' => ['department_id' => request_integer('department_id'), 'job_title' => request_string('job_title')],
        'version' => null,
        'duties' => [],
        'models' => $models,
        'departments' => find_departments($pdo),
        'managerOptions' => find_manager_options($pdo),
        'locationOptions' => find_home_location_options($pdo),
        'promptOptions' => find_active_system_prompt_options($pdo),
        'subagentOptions' => find_subagent_options($pdo),
        'toolEndpointOptions' => find_grantable_tool_endpoints($pdo),
        'errors' => [],
    ]),
    ['activeNav' => 'nav-agents', 'screen' => 'agent-hire']);
