<?php
declare(strict_types=1);

/**
 * Action `agent_hire` — log `agent.hire`. Gate: mod:hr. Creates four things in one
 * transaction: the members row, the agent_profiles row, version 1, and the location_residents
 * row at the home location. Control no longer refuses anything (db/094 reversed db/067): an
 * agent may live at an unmanaged host, which the screens record and show rather than veto.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_module_grant('hr');
agent_refuse_agent_caller();
require_post();
verify_csrf();

$pdo = db();
[$fields, $errors] = agent_hire_fields_from_request();

if ($fields['model_id'] !== null && ($chosenModel = find_model($pdo, $fields['model_id'])) === null) {
    $errors[] = 'Choose a model that exists.';
} elseif ($fields['model_id'] !== null && ($harnessProblem = agent_harness_error($chosenModel)) !== null) {
    // Hiring onto a harness nobody has built produces an agent the roster shows as working and
    // that fails at dispatch — which is exactly how Johnathan, Claude and Audi sat idle for two
    // days (docs/build-specs/agent-runtime-claude-sdk.md).
    $errors[] = $harnessProblem;
}
if ($fields['department_id'] !== null && find_department($pdo, $fields['department_id']) === null) {
    $errors[] = 'Choose a department that exists.';
}
// A manager is a person or an orchestrator agent (2026-09-18). The picker offers only those,
// so this catches a caller that did not come through the picker — the assistant, an agent, or
// a stale form — rather than second-guessing the screen.
if ($fields['manager_member_id'] !== null
    && ($managerProblem = agent_manager_error($pdo, $fields['manager_member_id'], null)) !== null) {
    $errors[] = $managerProblem;
}

$renderForm = function (array $errs) use ($pdo, $fields): never {
    emit_action_status(false, ['errors' => $errs]);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    echo view('agents/agent-form.php', [
        'isEdit' => false,
        'agent' => $fields,
        'version' => null,
        'duties' => [],
        'models' => find_models($pdo, false),
        'departments' => find_departments($pdo),
        'managerOptions' => find_manager_options($pdo),
        'locationOptions' => find_home_location_options($pdo),
        'promptOptions' => find_active_system_prompt_options($pdo),
        'subagentOptions' => find_subagent_options($pdo),
        'toolEndpointOptions' => find_grantable_tool_endpoints($pdo),
        'errors' => $errs,
    ]);
    exit;
};

if ($errors !== []) {
    $renderForm($errors);
}
if (find_models($pdo, false) === []) {
    $renderForm(['Register a model first, at /settings/models/new.']);
}

[$fields, $promptErrors] = resolve_agent_prompt_selection($pdo, $fields);
if ($promptErrors !== []) {
    $renderForm($promptErrors);
}

check_approval($pdo, 'agent_hire', 'agent.hire', 'Hire ' . $fields['name'], $fields);

try {
    $agent = hire_agent($pdo, $fields, (int) current_member_id());
} catch (PDOException $ex) {
    error_log('agent hire failed: ' . $ex->getMessage());
    if ($ex->getCode() === '23505') {
        $renderForm(['An agent (or another member) already exists with that email.']);
    }
    // A trigger's own words are written for a person and are worth showing; the driver's
    // wrapper around them is not. This used to try to cut one particular message down with a
    // regex, and when that regex stopped matching the whole SQLSTATE string went to the screen.
    $renderForm([db_message($ex, 'The agent could not be hired.')]);
} catch (RuntimeException $ex) {
    $renderForm([$ex->getMessage()]);
}
if ($agent === []) {
    $renderForm(['The agent could not be hired.']);
}

$memberId = (int) $agent['agent_member_id'];

// The photo was validated before the hire; now there is an id to store it under. A storage
// failure must not unmake a hired agent, so it is reported on the agent's own page instead.
$photoError = null;
if (($fields['photo'] ?? null) !== null) {
    try {
        store_agent_photo($pdo, $memberId, $fields['photo']);
        $agent = find_agent($pdo, $memberId) ?? $agent;
    } catch (RuntimeException $ex) {
        $photoError = $ex->getMessage();
        error_log('agent photo store failed: ' . $ex->getMessage());
    }
}

log_activity($pdo, 'agent.hire', 'member', $memberId, [
    'after' => ['name' => $agent['display_name'], 'job_title' => $agent['job_title'], 'status' => $agent['status']],
]);
emit_action_status(true, ['did' => 'Hired ' . $agent['display_name'] . ' as a candidate', 'refresh' => 'agentChanged']);
hx_trigger('agentChanged');
render_agent_page($pdo, $memberId, 'job', $photoError !== null ? [$photoError] : []);
