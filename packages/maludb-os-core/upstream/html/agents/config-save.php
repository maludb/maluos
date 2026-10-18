<?php
declare(strict_types=1);

/**
 * Action `agent_update_config` — log `agent_config_version.create`. Gate: mod:hr, agent's
 * manager (OR). Never edits a version; always creates the next one. Duty rows submitted here
 * are applied (upsert/remove) BEFORE the new version is written, so its schedule snapshot
 * reflects them; tool grants are edited live via tool-grant.php / tool-revoke.php and are
 * simply snapshotted as they stand.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_post();
verify_csrf();

$pdo = db();
$id = request_integer('agent');
if ($id === null || ($agent = find_agent($pdo, $id)) === null) {
    http_response_code(404);
    exit('Agent not found.');
}
agent_require_hr_or_manager($pdo, $agent);
agent_refuse_agent_caller();

[$fields, $errors] = agent_config_fields_from_request();
if ($fields['model_id'] !== null && find_model($pdo, $fields['model_id']) === null) {
    $errors[] = 'Choose a model that exists.';
}
// The kind is the record's, never the form's: only a voice agent may carry a number (db/093).
$errors = array_merge($errors,
    agent_phone_errors($fields['phone_number'], (string) ($agent['agent_kind'] ?? 'subagent')));

$renderForm = function (array $errs) use ($pdo, $id, $agent, $fields): never {
    emit_action_status(false, ['errors' => $errs]);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    echo view('agents/agent-form.php', [
        'isEdit' => true,
        'agent' => $agent,
        'version' => array_merge($fields, ['agent_member_id' => $id]),
        'duties' => find_agent_duties($pdo, $id),
        'models' => find_models($pdo, false),
        'departments' => [], 'managerOptions' => [], 'locationOptions' => [],
        'promptOptions' => find_active_system_prompt_options($pdo),
        'errors' => $errs,
    ]);
    exit;
};

if ($errors !== []) {
    $renderForm($errors);
}

[$fields, $promptErrors] = resolve_agent_prompt_selection($pdo, $fields);
if ($promptErrors !== []) {
    $renderForm($promptErrors);
}

check_approval($pdo, 'agent_update_config', 'agent_config_version.create',
    'Update configuration for ' . $agent['display_name'], $fields, 'member', $id);

$existingDutyIds = array_map(static fn ($d) => (int) $d['duty_id'], find_agent_duties($pdo, $id));
try {
    foreach ($fields['duties'] as $duty) {
        if ($duty['duty_id'] !== null && !in_array($duty['duty_id'], $existingDutyIds, true)) {
            continue;                                  // not this agent's duty — ignore rather than 500
        }
        if ($duty['remove']) {
            if ($duty['duty_id'] !== null) {
                remove_agent_duty($pdo, $duty['duty_id']);
            }
            continue;
        }
        upsert_agent_duty($pdo, $id, $duty['duty_id'], $duty);
    }
    update_agent_identity($pdo, $id, $fields);
    // The photo is a file, not a versioned setting: a new upload replaces it, the checkbox
    // removes it, and neither writes a configuration version of its own.
    if (($fields['photo'] ?? null) !== null) {
        store_agent_photo($pdo, $id, $fields['photo']);
    } elseif (!empty($fields['remove_photo'])) {
        clear_agent_photo($pdo, $id);
    }
    $version = create_config_version($pdo, $id, $fields, (int) current_member_id());
} catch (PDOException $ex) {
    error_log('agent config save failed: ' . $ex->getMessage());
    $renderForm(['The configuration could not be saved.']);
} catch (RuntimeException $ex) {
    error_log('agent photo store failed: ' . $ex->getMessage());
    $renderForm([$ex->getMessage()]);
}
if ($version === []) {
    $renderForm(['The configuration could not be saved.']);
}

log_activity($pdo, 'agent_config_version.create', 'member', $id, [
    'after' => ['version_no' => $version['version_no'], 'change_note' => $version['change_note']],
]);
emit_action_status(true, [
    'did' => 'Created configuration version ' . $version['version_no'] . ' for ' . $agent['display_name'],
    'refresh' => 'agentChanged',
]);
hx_trigger('agentChanged');
render_agent_page($pdo, $id, 'job');
