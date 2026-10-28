<?php
declare(strict_types=1);

/**
 * Agent HR presenters. Whitelists, mirrored by web/lib/schemas/agents.ts
 * (docs/react-migration-plan.md, "Presenters, never raw rows").
 *
 * mcp_agents and mcp_agent_config_versions already hide job_description, grants and budget
 * from a caller app_can_see_agent() does not admit — a plain insider's row simply arrives with
 * NULLs, and these functions pass on what arrived. Nothing here reads a base table.
 *
 * Never presented: an endpoint's url, a photo's sha256 / mime / size, a version's tool_grants
 * and schedule snapshots, a review's metrics, who created / activated / granted — no template
 * printed them.
 */

require_once dirname(__DIR__) . '/team/present.php';

const AGENT_HR_EVENT_LABELS = [
    'hire' => 'Hired', 'onboard' => 'Onboarded (activated)', 'adjust' => 'Configuration changed',
    'review' => 'Reviewed', 'suspend' => 'Suspended', 'reinstate' => 'Reinstated',
    'offboard' => 'Offboarded', 'department_change' => 'Department changed', 'manager_change' => 'Manager changed',
];
const ESCALATION_REASON_LABELS = [
    'needs_approval' => 'Needs approval', 'uncertain' => 'Uncertain', 'blocked' => 'Blocked',
    'policy' => 'Policy', 'error' => 'Error', 'budget' => 'Budget', 'other' => 'Other',
];

/**
 * What every picture of an agent needs — agent_avatar_html()'s two inputs.
 *
 * The photo's address is the same before and after a new upload (/agents/photo.php?agent=N), so
 * a browser that already holds the old picture goes on showing it. When the row carries
 * profile_photo_updated_at (mcp_agents does), the address leaves with it as `&v=<unix time>`:
 * a new picture is a new address. photo.php ignores the parameter.
 */
function present_agent_avatar(array $a): array
{
    $url = trim((string) ($a['profile_pic_url'] ?? ''));
    $updated = strtotime((string) ($a['profile_photo_updated_at'] ?? ''));
    if ($url !== '' && $updated !== false && str_starts_with($url, '/agents/photo.php?')) {
        $url .= '&v=' . $updated;
    }
    return [
        'initials' => agent_initials((string) ($a['display_name'] ?? '')),
        'picture_url' => $url !== '' ? $url : null,
    ];
}

/** One row of the agents list (find_agents()). */
function present_agent_row(array $a): array
{
    $kind = (string) ($a['agent_kind'] ?? 'subagent');
    return [
        'id' => (int) $a['agent_member_id'],
        'name' => (string) $a['display_name'],
        'avatar' => present_agent_avatar($a),
        'department_name' => $a['department_name'] ?? null,
        // Click-around step 3 (db/151): the department and the model as links.
        'department_id' => isset($a['department_id']) ? (int) $a['department_id'] : null,
        'model_id' => isset($a['model_id']) ? (int) $a['model_id'] : null,
        'role_key' => $a['role_key'] ?? null,
        'kind' => $kind,
        'kind_label' => AGENT_KIND_LABELS[$kind] ?? ucfirst($kind),
        'subagent_count' => (int) ($a['subagent_count'] ?? 0),
        'job_title' => $a['job_title'] ?? null,
        // The profile description, shown on the card (2026-09-29).
        'description' => trim((string) ($a['description'] ?? '')) !== '' ? trim((string) $a['description']) : null,
        'manager_name' => $a['manager_name'] ?? null,
        'manager_member_id' => isset($a['manager_member_id']) ? (int) $a['manager_member_id'] : null,
        'model_key' => $a['model_key'] ?? null,
        'status' => (string) $a['status'],
    ];
}

/** An agent, for its page, its config history and its edit form (find_agent()). */
function present_agent(array $a): array
{
    $int = static fn (string $k): ?int => isset($a[$k]) && $a[$k] !== '' ? (int) $a[$k] : null;
    $text = static fn (string $k): ?string => ($a[$k] ?? '') !== '' ? (string) $a[$k] : null;
    $kind = (string) ($a['agent_kind'] ?? 'subagent');
    return [
        'id' => $int('agent_member_id'),
        'name' => (string) ($a['display_name'] ?? ''),
        'avatar' => present_agent_avatar($a),
        'email' => $text('email'),
        'departments' => present_pg_names($a['departments'] ?? null),
        'department_id' => $int('department_id'),          // hire prefill only
        'job_title' => $text('job_title'),
        'status' => (string) ($a['status'] ?? 'candidate'),
        'kind' => $kind,
        'kind_label' => AGENT_KIND_LABELS[$kind] ?? ucfirst($kind),
        'subagent_count' => (int) ($a['subagent_count'] ?? 0),
        'description' => $text('description'),
        'role_key' => $text('role_key'),
        'phone_number' => $text('phone_number'),
        'manager_member_id' => $int('manager_member_id'),
        'manager_name' => $text('manager_name'),
        'manager_kind' => $text('manager_kind'),                // find_agent() only; the manager's page
        'home_location_id' => $int('home_location_id'),
        'home_location_name' => $text('home_location_name'),   // find_agent() only
        'model_key' => $text('model_key'),
        'harness' => $text('harness'),
        'budget_currency' => $text('budget_currency'),
        'hired_at' => json_ts($a['hired_at'] ?? null),
    ];
}

/** A version's resolved model parameters, decoded (agent_config_versions.harness_config). */
function agent_version_parameters(array $v): array
{
    if (($v['harness_config'] ?? null) === null) {
        return [];
    }
    $decoded = json_decode((string) $v['harness_config'], true);
    return is_array($decoded) ? $decoded : [];
}

/**
 * A configuration version as the Job tab and the config history show it
 * (find_agent_version() / find_agent_versions()). Parameters travel as the one-line summary
 * those screens printed — the full map is for the edit form alone (present_agent_version_form()).
 */
function present_agent_version(array $v, ?string $currency, bool $withText = true): array
{
    $promptId = ($v['system_prompt_id'] ?? null) !== null ? (int) $v['system_prompt_id'] : null;
    $activated = ($v['activated_at'] ?? null) !== null;
    return [
        'id' => (int) $v['config_version_id'],
        'version_no' => (int) $v['version_no'],
        // The config history lists versions without their text; only the Job tab prints it.
        'job_description' => $withText ? ($v['job_description'] ?? null) : null,
        'system_prompt' => $promptId === null ? null : [
            'id' => $promptId,
            'name' => (string) ($v['system_prompt_name'] ?? $v['system_prompt_key'] ?? 'Library prompt'),
            'version' => (int) $v['system_prompt_version'],
        ],
        'parameters_summary' => prompt_parameters_summary(agent_version_parameters($v)),
        'run_limits' => agent_version_run_limits($v),
        'monthly_budget_display' => ($v['monthly_budget_amount'] ?? null) !== null
            ? money((string) $v['monthly_budget_amount'], $currency ?? 'USD') : null,
        'change_note' => ($v['change_note'] ?? '') !== '' ? $v['change_note'] : null,
        'created_at' => json_ts($v['created_at'] ?? null),
        'activated_at' => json_ts($v['activated_at'] ?? null),
        'gated' => $activated && ($v['gating_eval_run_id'] ?? null) !== null,
        // Click-around step 2: the model and the gating run as links, not only as facts.
        'model_id' => ($v['model_id'] ?? null) !== null ? (int) $v['model_id'] : null,
        'model_name' => ($v['model_name'] ?? '') !== '' ? (string) $v['model_name'] : null,
        'gating_eval_run_id' => $activated && ($v['gating_eval_run_id'] ?? null) !== null ? (int) $v['gating_eval_run_id'] : null,
    ];
}

/**
 * The version the edit form starts from (mod:hr only — html/agents/form.php's gate). Carries
 * what the form's fields show: the prompt choice, the inline text, the cited parameters when a
 * library prompt is chosen, or the inline parameter fields' values when not.
 */
function present_agent_version_form(?array $v): ?array
{
    if ($v === null) {
        return null;
    }
    $promptId = ($v['system_prompt_id'] ?? null) !== null ? (int) $v['system_prompt_id'] : null;
    $params = agent_version_parameters($v);
    $cited = [];
    foreach ($promptId !== null ? $params : [] as $k => $value) {
        $cited[] = ['name' => (string) $k, 'value' => is_scalar($value) ? (string) $value : (string) json_encode($value)];
    }
    $inline = split_prompt_parameters($promptId === null ? $params : []);
    return [
        'model_id' => ($v['model_id'] ?? null) !== null ? (int) $v['model_id'] : null,
        'system_prompt_id' => $promptId,
        'job_description' => (string) ($v['job_description'] ?? ''),
        'cited_parameters' => $cited,
        'inline_parameters' => [
            'temperature' => (string) $inline['temperature'],
            'max_tokens' => (string) $inline['max_tokens'],
            'thinking_budget' => (string) $inline['thinking_budget'],
            'extra_parameters' => (string) $inline['extra_parameters'],
        ],
        'monthly_budget_amount' => ($v['monthly_budget_amount'] ?? null) !== null
            ? (string) $v['monthly_budget_amount'] : null,
        'run_limits' => agent_version_run_limits($v),
    ];
}

/** The two run limits a person sets, out of runtime_config — never the whole object: what else
 *  it holds belongs to the harness. Empty string = not set, the runner's default applies. */
function agent_version_run_limits(array $v): array
{
    $runtime = $v['runtime_config'] ?? [];
    $runtime = is_string($runtime) ? (json_decode($runtime, true) ?: []) : (is_array($runtime) ? $runtime : []);
    $limits = [];
    foreach (['max_turns', 'run_timeout_seconds'] as $key) {
        $limits[$key] = is_int($runtime[$key] ?? null) ? (string) $runtime[$key] : '';
    }
    return $limits;
}

/** One live tool grant (find_agent_tool_grants()). */
function present_agent_tool_grant(array $g): array
{
    $constraints = $g['constraints'] ?? '{}';
    $constraints = is_string($constraints) ? $constraints : (string) json_encode($constraints);
    return [
        'id' => (int) ($g['agent_tool_grant_id'] ?? 0),
        'endpoint_id' => (int) ($g['application_endpoint_id'] ?? 0),
        'application_id' => ($g['application_id'] ?? null) !== null ? (int) $g['application_id'] : null,
        'application_name' => (string) ($g['application_name'] ?? ''),
        'endpoint_name' => (string) ($g['endpoint_name'] ?? ''),
        'tool_name' => (string) $g['tool_name'],
        'constraints' => $constraints !== '{}' ? $constraints : null,
    ];
}

/** An MCP endpoint offered in a tool picker (find_grantable_tool_endpoints()) — never its url. */
function present_tool_endpoint_option(array $e): array
{
    return ['id' => (int) $e['application_endpoint_id'],
            'name' => $e['application_name'] . ' — ' . $e['endpoint_name']];
}

/** One duty (find_agent_duties()). */
function present_agent_duty(array $d): array
{
    return [
        'id' => (int) $d['duty_id'],
        'name' => (string) $d['name'],
        'instructions' => (string) ($d['instructions'] ?? ''),
        'schedule_cron' => (string) $d['schedule_cron'],
        'timezone' => (string) $d['timezone'],
        'next_run_at' => json_ts($d['next_run_at'] ?? null),
        'active' => !empty($d['active']),
    ];
}

/** One employment-record event (find_hr_events()). */
function present_hr_event(array $e): array
{
    $type = (string) $e['event_type'];
    return [
        'id' => (int) $e['hr_event_id'],
        'occurred_at' => json_ts($e['occurred_at'] ?? null),
        'label' => AGENT_HR_EVENT_LABELS[$type] ?? ucfirst($type),
        'note' => ($e['note'] ?? '') !== '' ? $e['note'] : null,
    ];
}

/** One performance review (find_performance_reviews()). */
function present_performance_review(array $r): array
{
    return [
        'id' => (int) $r['review_id'],
        'period_start' => (string) $r['period_start'],
        'period_end' => (string) $r['period_end'],
        'rating' => $r['rating'] !== null ? (int) $r['rating'] : null,
        'summary' => ($r['summary'] ?? '') !== '' ? $r['summary'] : null,
    ];
}

/** One approval request the agent raised (find_agent_approval_requests()). */
function present_agent_approval_request(array $a): array
{
    return ['id' => (int) $a['approval_request_id'], 'summary' => (string) $a['summary'], 'status' => (string) $a['status'],
            'agent_run_id' => isset($a['agent_run_id']) ? (int) $a['agent_run_id'] : null,
            'approver_name' => $a['approver_name'] ?? null,
            'approver_member_id' => ($a['approver_member_id'] ?? null) !== null ? (int) $a['approver_member_id'] : null,
            'created_at' => json_ts($a['created_at'] ?? null),
            'expires_at' => json_ts($a['expires_at'] ?? null), 'decided_at' => json_ts($a['decided_at'] ?? null)];
}

/** One roster row, from whichever side the page shows (find_agent_roster() / find_agent_orchestrators()). */
function present_roster_row(array $r, bool $orchestratorSide): array
{
    return [
        'member_id' => (int) ($orchestratorSide ? $r['subagent_member_id'] : $r['orchestrator_member_id']),
        'name' => (string) ($orchestratorSide ? $r['subagent_name'] : $r['orchestrator_name']),
        'role_key' => $orchestratorSide ? ($r['subagent_role_key'] ?? null) : null,
        'status' => $orchestratorSide ? (string) $r['subagent_status'] : null,
        'note' => ($r['note'] ?? '') !== '' ? $r['note'] : null,
        'added_at' => json_ts($r['added_at'] ?? null),
    ];
}

/** Someone who may manage an agent (find_manager_options()): a person, or an orchestrator. */
function present_manager_option(array $m): array
{
    return ['id' => (int) $m['member_id'], 'name' => (string) $m['display_name'],
            'kind' => (string) ($m['member_kind'] ?? 'human')];
}

/** An agent offered in a picker (find_subagent_options() / find_agent_member_options()). */
function present_agent_option(array $a): array
{
    return ['id' => (int) $a['member_id'], 'name' => (string) $a['display_name']];
}

/** An active model offered on the form (find_models()). */
function present_model_option(array $m): array
{
    $plan = ($m['auth_mode'] ?? 'api_key') === 'claude_subscription' && stripos((string) $m['display_name'], 'max plan') === false ? ' · Max plan' : '';
    return ['id' => (int) $m['model_id'], 'name' => $m['display_name'] . $plan . ' (' . $m['harness'] . ')'];
}

/** A library prompt offered on the form (find_active_system_prompt_options()). */
function present_prompt_option(array $p): array
{
    return ['id' => (int) $p['system_prompt_id'], 'name' => $p['name'] . ' (v' . (int) $p['current_version'] . ')'];
}

/** An office or desk offered as a home location (find_home_location_options()). */
function present_home_location_option(array $l): array
{
    return ['id' => (int) $l['location_id'], 'name' => $l['name'] . ' (' . ucfirst((string) $l['kind']) . ')'];
}

/** One escalation (find_escalations()). */
function present_escalation(array $e): array
{
    return [
        'id' => (int) $e['escalation_id'],
        'agent_member_id' => (int) $e['agent_member_id'],
        'agent_name' => (string) $e['agent_name'],
        'reason_label' => ESCALATION_REASON_LABELS[$e['reason_kind']] ?? (string) $e['reason_kind'],
        'summary' => (string) $e['summary'],
        'to_member_id' => $e['to_member_id'] !== null ? (int) $e['to_member_id'] : null,
        // Click-around step 3 (db/151): the recipient by name, to their page.
        'to_member_name' => ($e['to_member_name'] ?? null) !== null ? (string) $e['to_member_name'] : null,
        'to_member_kind' => ($e['to_member_kind'] ?? null) !== null ? (string) $e['to_member_kind'] : null,
        'created_at' => json_ts($e['created_at'] ?? null),
        'resolved' => $e['resolved_at'] !== null,
        // Click-around step 2: what it is about, and the approval it waits on, as links.
        'approval_request_id' => ($e['approval_request_id'] ?? null) !== null ? (int) $e['approval_request_id'] : null,
        'entity_type' => ($e['entity_type'] ?? '') !== '' ? (string) $e['entity_type'] : null,
        'entity_id' => ($e['entity_id'] ?? null) !== null ? (int) $e['entity_id'] : null,
    ];
}

/**
 * One chat turn (agent-chat.md): what the person said, what the agent answered, and where it stands.
 * The reply is shown once the run ended well or is held for an approval; an error only for a failure.
 */
function present_chat_turn(array $r): array
{
    $status = (string) $r['status'];
    $done = $status !== 'running';
    return [
        'run_id' => (int) $r['id'],
        'status' => $status,
        'finished' => $done,
        'said' => (string) ($r['chat_utterance'] ?? ''),
        'reply' => in_array($status, ['succeeded', 'awaiting_approval'], true) && ($r['result'] ?? '') !== '' ? (string) $r['result'] : null,
        'error' => $status === 'failed' ? (string) ($r['error'] ?? 'The run failed.') : null,
        'approval_request_id' => isset($r['approval_request_id']) ? (int) $r['approval_request_id'] : null,
        'cost' => isset($r['cost']) ? (string) $r['cost'] : null,
        'currency' => $r['currency'] ?? null,
        'started_at' => json_ts($r['started_at'] ?? null),
        'finished_at' => json_ts($r['finished_at'] ?? null),
    ];
}

/** A conversation in the Chat tab's list. */
function present_chat_conversation(array $c): array
{
    return [
        'id' => (int) $c['id'], 'title' => (string) $c['title'], 'turns' => (int) ($c['turns'] ?? 0),
        'created_at' => json_ts($c['created_at'] ?? null), 'last_at' => json_ts($c['last_at'] ?? null),
        'archived' => ($c['archived_at'] ?? null) !== null,
    ];
}
