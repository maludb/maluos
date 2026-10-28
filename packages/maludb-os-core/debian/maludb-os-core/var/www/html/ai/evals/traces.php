<?php
declare(strict_types=1);

/** Screen `graded-traces` — production runs graded by continuous evals (params: agent, eval_set, failed — click-around step 4 added the controls and the set). */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/records/present.php';

require_insider();
if (is_agent_member()) { deny('Evals are people\'s work — an agent cannot open them.'); }

$pdo = db();
log_screen_view($pdo, 'graded-traces');
$st = $pdo->prepare('SELECT g.*, (SELECT d.display_name FROM mcp_team_directory d WHERE d.member_id = g.agent_member_id) AS agent_name,
                               (SELECT s.name FROM mcp_eval_sets s WHERE s.eval_set_id = g.eval_set_id) AS eval_set_name FROM mcp_trace_grades g
                        WHERE (:a::bigint IS NULL OR g.agent_member_id = :a2) AND (:s::bigint IS NULL OR g.eval_set_id = :s2) AND (NOT :f::boolean OR g.passed = false) ORDER BY g.graded_at DESC NULLS LAST LIMIT 200');
$st->execute(['a' => request_integer('agent'), 'a2' => request_integer('agent'), 's' => request_integer('eval_set'), 's2' => request_integer('eval_set'), 'f' => request_bool('failed') ? 'true' : 'false']);
respond_screen(['traces' => array_map(static fn (array $g): array => ['id' => (int) $g['trace_grade_id'], 'agent_run_id' => (int) $g['agent_run_id'], 'agent_name' => $g['agent_name'] ?? null,
    'agent_member_id' => isset($g['agent_member_id']) ? (int) $g['agent_member_id'] : null, 'eval_set_name' => $g['eval_set_name'] ?? null,
    'eval_set_id' => $g['eval_set_id'] !== null ? (int) $g['eval_set_id'] : null, 'score' => $g['score'] !== null ? (string) $g['score'] : null, 'passed' => $g['passed'] !== null ? (bool) $g['passed'] : null,
    'grader_notes' => $g['grader_notes'] ?? null, 'graded_at' => json_ts($g['graded_at'] ?? null)], $st->fetchAll()),
    'filters' => ['agent' => request_integer('agent'), 'eval_set' => request_integer('eval_set'), 'failed' => request_bool('failed')], 'runner_built' => true,
    'options' => ['agents' => array_values(array_filter(array_map('present_member_option', selectable_members($pdo)), static fn (array $m): bool => $m['kind'] === 'agent')),
                  'sets' => array_map(static fn (array $s): array => ['id' => (int) $s['eval_set_id'], 'name' => (string) $s['name']], find_eval_sets($pdo))]]);
