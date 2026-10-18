<?php
declare(strict_types=1);

/** AI Ops presenters. Whitelists, mirrored by web/lib/schemas/aiops.ts. A list never carries a payload. */

function present_ledger_call(array $c): array
{
    $int = static fn (string $k): ?int => isset($c[$k]) && $c[$k] !== '' ? (int) $c[$k] : null;
    return [
        'id' => (int) $c['ledger_id'], 'occurred_at' => json_ts($c['occurred_at'] ?? null),
        'agent' => $int('agent_member_id') !== null ? ['id' => $int('agent_member_id'), 'name' => $c['agent_name'] ?? null] : null,
        'acting' => ['id' => (int) $c['acting_member_id'], 'name' => $c['acting_name'] ?? null],
        'run_id' => $int('agent_run_id'), 'harness' => (string) $c['harness'], 'provider' => (string) $c['provider'],
        'model_name' => $c['model_name'] ?? null, 'provider_model_id' => (string) $c['provider_model_id'],
        'request_id' => (string) $c['request_id'], 'call_kind' => (string) $c['call_kind'],
        'status' => (string) $c['status'], 'status_label' => AIOPS_CALL_STATUSES[$c['status']] ?? (string) $c['status'],
        'error_code' => $c['error_code'] ?? null, 'error_message' => $c['error_message'] ?? null,
        'input_tokens' => (int) $c['input_tokens'], 'output_tokens' => (int) $c['output_tokens'],
        'cache_read_tokens' => (int) $c['cache_read_tokens'], 'cache_write_tokens' => (int) $c['cache_write_tokens'],
        'latency_ms' => $int('latency_ms'), 'cost' => (string) $c['cost'], 'currency' => (string) $c['currency'],
        'payload_expired' => ($c['payload_archived_at'] ?? null) !== null,
        // Click-around step 2 (additive): the model's registry id and the application the call served.
        'model_id' => $int('model_id'), 'application_id' => $int('application_id'),
    ];
}

/** One side of a stored payload as readable text: pretty JSON, capped. Never HTML — the page shows it pre-wrapped. */
function present_payload_side(mixed $json): array
{
    $decoded = is_string($json) ? json_decode($json, true) : $json;
    $text = $decoded === null ? '' : (string) json_encode($decoded, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
    $length = strlen($text);
    return ['text' => $length > AIOPS_PAYLOAD_CAP ? mb_strcut($text, 0, AIOPS_PAYLOAD_CAP) : $text, 'truncated' => $length > AIOPS_PAYLOAD_CAP, 'bytes' => $length];
}

function present_ops_run(array $r): array
{
    $int = static fn (string $k): ?int => isset($r[$k]) && $r[$k] !== '' ? (int) $r[$k] : null;
    return [
        'id' => (int) $r['agent_run_id'], 'agent' => ['id' => (int) $r['agent_member_id'], 'name' => $r['agent_name'] ?? null],
        'trigger' => (string) $r['trigger'], 'status' => (string) $r['status'], 'error' => $r['error'] ?? null,
        'model_name' => $r['model_name'] ?? null, 'harness' => $r['harness'] ?? null, 'request_id' => $r['request_id'] ?? null,
        'requested_by_name' => $r['requested_by_name'] ?? null, 'duty_name' => $r['duty_name'] ?? null,
        'parent_run_id' => $int('parent_run_id'), 'approval_request_id' => $int('approval_request_id'),
        'config_version_id' => $int('config_version_id'), 'project_id' => $int('project_id'), 'task_id' => $int('task_id'),
        'input_tokens' => (int) $r['input_tokens'], 'output_tokens' => (int) $r['output_tokens'],
        'cache_read_tokens' => (int) $r['cache_read_tokens'], 'cache_write_tokens' => (int) $r['cache_write_tokens'],
        'cost' => (string) $r['cost'], 'currency' => (string) $r['currency'],
        'started_at' => json_ts($r['started_at'] ?? null), 'finished_at' => json_ts($r['finished_at'] ?? null),
        'instructions' => isset($r['instructions']) ? mb_substr((string) $r['instructions'], 0, 20000) : null,
        'result' => isset($r['result']) ? mb_substr((string) $r['result'], 0, 40000) : null,
        // Click-around step 2 (additive): the model's registry id, who asked (with the kind that decides their page), the application served.
        'model_id' => $int('model_id'),
        'requested_by' => $int('requested_by') !== null ? ['id' => $int('requested_by'), 'name' => $r['requested_by_name'] ?? null, 'kind' => $r['requested_by_kind'] ?? null] : null,
        'acting_member_id' => $int('acting_member_id'), 'application_id' => $int('application_id'),
    ];
}

/**
 * The verdicts on one run or call: this caller's own (so the buttons can show what they said)
 * and everyone's (so a later evaluation, and the next reader, can see the label). db/124.
 */
function present_verdicts(?array $mine, array $all): array
{
    return [
        'mine' => $mine === null ? null
            : ['verdict' => (string) $mine['verdict'], 'note' => $mine['note'] ?? null,
               'updated_at' => json_ts($mine['updated_at'] ?? null)],
        'all' => array_map(static fn (array $v): array => [
            'verdict' => (string) $v['verdict'], 'note' => $v['note'] ?? null,
            'member_name' => $v['member_name'] ?? null, 'member_id' => isset($v['member_id']) ? (int) $v['member_id'] : null,
            'updated_at' => json_ts($v['updated_at'] ?? null),
        ], $all),
    ];
}

/** One row of what happened inside a run (db/122). */
function present_run_event(array $e): array
{
    return [
        'seq' => (int) $e['seq'], 'at' => json_ts($e['occurred_at']), 'event' => (string) $e['event'],
        'tool_name' => $e['tool_name'] ?? null, 'status' => $e['status'] ?? null,
        'duration_ms' => $e['duration_ms'] !== null ? (int) $e['duration_ms'] : null,
        'error' => $e['error_message'] ?? $e['error_type'] ?? null,
    ];
}

/** One period of an agent's model usage (summarise_agent_ledger()). */
function present_agent_ledger_period(array $r): array
{
    return ['calls' => (int) $r['calls'], 'failed' => (int) $r['failed'], 'input_tokens' => (int) $r['input_tokens'], 'output_tokens' => (int) $r['output_tokens'],
            'cache_read_tokens' => (int) $r['cache_read_tokens'], 'avg_latency_ms' => $r['avg_latency_ms'] !== null ? (int) $r['avg_latency_ms'] : null,
            'cost' => number_format((float) $r['cost'], 6, '.', ''), 'currency' => (string) $r['currency'], 'last_at' => json_ts($r['last_at'] ?? null)];
}

function present_ai_spend_row(array $r): array
{
    return ['key' => $r['group_key'] !== null ? (string) $r['group_key'] : null, 'kind' => $r['kind'] ?? null, 'label' => (string) $r['label'], 'calls' => (int) $r['calls'], 'failed' => (int) $r['failed'],
            'input_tokens' => (int) $r['input_tokens'], 'output_tokens' => (int) $r['output_tokens'], 'cache_read_tokens' => (int) $r['cache_read_tokens'],
            'cache_write_tokens' => (int) $r['cache_write_tokens'], 'avg_latency_ms' => $r['avg_latency_ms'] !== null ? (int) $r['avg_latency_ms'] : null,
            'cost' => (string) $r['cost'], 'currency' => (string) $r['currency'], 'cache_saving' => number_format((float) $r['cache_saving'], 4, '.', '')];
}

function present_eval_set(array $s): array
{
    $int = static fn (string $k): ?int => isset($s[$k]) && $s[$k] !== '' ? (int) $s[$k] : null;
    return ['id' => $int('eval_set_id'), 'name' => (string) ($s['name'] ?? ''), 'description' => $s['description'] ?? null,
            'agent' => $int('agent_member_id') !== null ? ['id' => $int('agent_member_id'), 'name' => $s['agent_name'] ?? null] : null,
            'role_key' => $s['role_key'] ?? null, 'department_id' => $int('department_id'), 'department_name' => $s['department_name'] ?? null,
            'pass_threshold' => (string) ($s['pass_threshold'] ?? '80'), 'status' => (string) ($s['status'] ?? 'active'),
            'status_label' => EVAL_SET_STATUSES[$s['status'] ?? 'active'] ?? 'Active', 'case_count' => (int) ($s['case_count'] ?? 0),
            'active_case_count' => (int) ($s['active_case_count'] ?? 0), 'schedule_count' => (int) ($s['schedule_count'] ?? 0),
            // The Auditor's trace checks (db/145), as saved.
            'trace_checks' => isset($s['trace_checks']) && $s['trace_checks'] !== null ? (is_string($s['trace_checks']) ? json_decode($s['trace_checks'], true) : $s['trace_checks']) : null,
        ];
}

/** jsonb {"text": "..."} (what the forms write) → its text; anything else → pretty JSON. */
function eval_json_text(mixed $json): ?string
{
    if ($json === null) { return null; }
    $d = is_string($json) ? json_decode($json, true) : $json;
    if (is_array($d) && array_keys($d) === ['text'] && is_string($d['text'])) { return $d['text']; }
    return is_string($d) ? $d : (string) json_encode($d, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
}

function present_eval_case(array $c): array
{
    $int = static fn (string $k): ?int => isset($c[$k]) && $c[$k] !== '' ? (int) $c[$k] : null;
    return ['id' => $int('eval_case_id'), 'eval_set_id' => (int) $c['eval_set_id'], 'title' => (string) ($c['title'] ?? ''),
            'input' => mb_substr((string) (eval_json_text($c['input'] ?? null) ?? ''), 0, 60000), 'expected' => eval_json_text($c['expected'] ?? null),
            'rubric' => $c['rubric'] ?? null, 'grader' => (string) ($c['grader'] ?? 'rubric_llm'), 'grader_label' => EVAL_GRADERS[$c['grader'] ?? 'rubric_llm'] ?? null,
            'weight' => (string) ($c['weight'] ?? '1'), 'origin' => (string) ($c['origin'] ?? 'authored'),
            'source_ledger_id' => $int('source_ledger_id'), 'source_run_id' => $int('source_run_id'), 'active' => !array_key_exists('active', $c) || !empty($c['active']),
            // JEV checks (db/144), as saved.
            'checks' => isset($c['checks']) && $c['checks'] !== null ? (is_string($c['checks']) ? json_decode($c['checks'], true) : $c['checks']) : null];
}

/**
 * What JEV answered for one result, trial by trial (db/144): each check's outcome and what it said.
 * Probabilities stay out (they are in the ledger); the reader needs outcome, value and confidence.
 */
function present_eval_jev_detail(mixed $detail): ?array
{
    $d = is_string($detail) ? json_decode($detail, true) : $detail;
    if (!is_array($d) || ($d['grader'] ?? null) !== 'jev') { return null; }
    $trials = [];
    foreach ((array) ($d['trials'] ?? []) as $i => $t) {
        $checks = [];
        foreach ((array) ($t['checks'] ?? []) as $id => $o) {
            $checks[] = ['id' => (string) $id, 'outcome' => (string) ($o['outcome'] ?? 'uncertain'),
                         'value' => isset($o['value']) ? round((float) $o['value'], 3) : null,
                         'choice' => $o['choice'] ?? null, 'level' => isset($o['level']) ? (int) $o['level'] : null,
                         'confidence' => isset($o['confidence']) ? round((float) $o['confidence'], 3) : null];
        }
        $trials[] = ['trial' => $i + 1, 'verdict' => (string) ($t['verdict'] ?? 'awaiting'), 'score' => $t['score'] ?? null,
                     'guard' => isset($t['guard']) ? round((float) $t['guard'], 3) : null, 'error' => $t['error'] ?? null, 'checks' => $checks];
    }
    return ['verdict' => (string) ($d['verdict'] ?? 'awaiting'), 'model' => $d['model'] ?? null, 'trials' => $trials];
}

/** One check's calibration row (mcp_eval_check_calibration). */
function present_eval_calibration(array $r): array
{
    $graded = (int) $r['person_graded'];
    return ['check_id' => (string) $r['check_id'], 'answers' => (int) $r['answers'], 'passes' => (int) $r['passes'],
            'fails' => (int) $r['fails'], 'uncertain' => (int) $r['uncertain'], 'person_graded' => $graded,
            'person_agreed' => (int) $r['person_agreed'],
            'agreement' => $graded > 0 ? round(100 * (int) $r['person_agreed'] / $graded, 1) : null,
            'mean_confidence' => $r['mean_confidence'] !== null ? (float) $r['mean_confidence'] : null];
}

function present_eval_schedule(array $h): array
{
    return ['id' => (int) $h['eval_schedule_id'], 'eval_set_id' => (int) $h['eval_set_id'], 'eval_set_name' => (string) $h['eval_set_name'], 'agent_name' => $h['agent_name'] ?? null,
            'kind' => (string) $h['kind'], 'kind_label' => EVAL_SCHEDULE_KINDS[$h['kind']] ?? (string) $h['kind'], 'cadence' => (string) $h['cadence'],
            'cadence_label' => EVAL_CADENCES[$h['cadence']] ?? (string) $h['cadence'], 'sample_size' => isset($h['sample_size']) ? (int) $h['sample_size'] : null,
            'regression_delta' => (string) $h['regression_delta'], 'active' => !empty($h['active']),
            'next_run_at' => json_ts($h['next_run_at'] ?? null), 'last_run_at' => json_ts($h['last_run_at'] ?? null),
            // Click-around step 2 (additive).
            'agent_member_id' => isset($h['agent_member_id']) ? (int) $h['agent_member_id'] : null,
            'last_eval_run_id' => isset($h['last_eval_run_id']) ? (int) $h['last_eval_run_id'] : null];
}

function present_eval_run(array $r): array
{
    return ['id' => (int) $r['eval_run_id'], 'eval_set_id' => (int) $r['eval_set_id'], 'eval_set_name' => (string) $r['eval_set_name'], 'trigger' => (string) $r['trigger'],
            'status' => (string) $r['status'], 'score' => $r['score'] !== null ? (string) $r['score'] : null, 'pass_threshold' => (string) $r['pass_threshold'],
            'cases_total' => (int) $r['cases_total'], 'cases_passed' => (int) $r['cases_passed'], 'cost' => (string) $r['cost'], 'currency' => (string) $r['currency'],
            'started_at' => json_ts($r['started_at'] ?? null), 'finished_at' => json_ts($r['finished_at'] ?? null),
            // Click-around step 2 (additive): who was evaluated, on what, against which run, started by whom.
            'agent_member_id' => isset($r['agent_member_id']) ? (int) $r['agent_member_id'] : null, 'agent_name' => $r['agent_name'] ?? null,
            'config_version_id' => isset($r['config_version_id']) ? (int) $r['config_version_id'] : null,
            'model_id' => isset($r['model_id']) ? (int) $r['model_id'] : null, 'model_name' => $r['model_name'] ?? null,
            'baseline_run_id' => isset($r['baseline_run_id']) ? (int) $r['baseline_run_id'] : null,
            'started_by' => isset($r['started_by']) ? ['id' => (int) $r['started_by'], 'name' => $r['started_by_name'] ?? null, 'kind' => $r['started_by_kind'] ?? null] : null];
}

function present_eval_alert(array $a): array
{
    return ['id' => (int) $a['eval_alert_id'], 'eval_set_id' => (int) $a['eval_set_id'], 'eval_set_name' => (string) $a['eval_set_name'],
            'agent' => isset($a['agent_member_id']) ? ['id' => (int) $a['agent_member_id'], 'name' => $a['agent_name'] ?? null] : null,
            'eval_run_id' => isset($a['eval_run_id']) ? (int) $a['eval_run_id'] : null, 'kind' => (string) $a['kind'], 'severity' => (string) $a['severity'],
            'score' => $a['score'] !== null ? (string) $a['score'] : null, 'baseline_score' => $a['baseline_score'] !== null ? (string) $a['baseline_score'] : null,
            'detail' => (string) $a['detail'], 'status' => (string) $a['status'], 'opened_at' => json_ts($a['opened_at'] ?? null),
            'acknowledged_at' => json_ts($a['acknowledged_at'] ?? null), 'resolved_at' => json_ts($a['resolved_at'] ?? null), 'resolution' => $a['resolution'] ?? null,
            // Click-around step 2 (additive).
            'schedule_id' => isset($a['schedule_id']) ? (int) $a['schedule_id'] : null,
            'acknowledged_by' => isset($a['acknowledged_by']) ? ['id' => (int) $a['acknowledged_by'], 'name' => $a['acknowledged_by_name'] ?? null, 'kind' => $a['acknowledged_by_kind'] ?? null] : null];
}
