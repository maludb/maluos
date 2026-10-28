<?php
declare(strict_types=1);

/**
 * Screen `audit` (GET /ai/audit/) — what the Auditor found (db/145): its findings and alerts on agent work,
 * the open eval alerts, and the real runs it graded — in shadow, what it would have done. People who may see
 * evals (the super-admin, or an admin of the Audit department). JSON only.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';

require_login();
if (!is_super_admin() && !is_business_admin()) { json_error('forbidden', 'The audit view is for the super-admin and Audit admins.', 403); }
$pdo = db();
log_screen_view($pdo, 'audit');
$ts = static fn ($v) => json_ts($v ?? null);
$decisions = $pdo->query("SELECT * FROM mcp_system_one_decisions WHERE playbook IN ('scheduled_evals', 'trace_sampling', 'evidence_integrity')
                           ORDER BY (decision <> 'record') DESC, created_at DESC LIMIT 100")->fetchAll();
$alerts = $pdo->query("SELECT * FROM mcp_eval_alerts WHERE status <> 'resolved' ORDER BY opened_at DESC LIMIT 50")->fetchAll();
$grades = $pdo->query("SELECT g.*, m.display_name AS agent_name FROM mcp_trace_grades g LEFT JOIN members m ON m.id = g.agent_member_id
                        ORDER BY g.graded_at DESC NULLS LAST LIMIT 50")->fetchAll();
$modes = $pdo->query("SELECT DISTINCT ON (agent_member_id) agent_member_id, agent_name, mode FROM mcp_system_one_decisions
                       WHERE playbook IN ('scheduled_evals', 'trace_sampling', 'evidence_integrity') ORDER BY agent_member_id, created_at DESC")->fetchAll();
respond_screen([
    'agents' => array_map(static fn (array $a): array => ['id' => (int) $a['agent_member_id'], 'name' => (string) $a['agent_name'], 'mode' => (string) $a['mode']], $modes),
    'decisions' => array_map(static fn (array $d): array => ['id' => (int) $d['decision_id'], 'agent_name' => (string) $d['agent_name'], 'playbook' => (string) $d['playbook'],
        'agent_run_id' => $d['agent_run_id'] !== null ? (int) $d['agent_run_id'] : null,
        'subject_kind' => (string) $d['subject_kind'], 'subject_id' => $d['subject_id'] !== null ? (int) $d['subject_id'] : null, 'subject' => (string) ($d['subject_label'] ?? ''),
        'decision' => (string) $d['decision'], 'mode' => (string) $d['mode'], 'acted' => (bool) $d['acted'], 'note' => $d['note'] ?? null, 'at' => $ts($d['created_at'])], $decisions),
    'alerts' => array_map(static fn (array $a): array => ['id' => (int) $a['eval_alert_id'], 'eval_set_name' => (string) ($a['eval_set_name'] ?? ''), 'kind' => (string) $a['kind'],
        'eval_set_id' => (int) $a['eval_set_id'], 'agent_member_id' => $a['agent_member_id'] !== null ? (int) $a['agent_member_id'] : null, 'agent_name' => $a['agent_name'] ?? null,
        'severity' => (string) $a['severity'], 'detail' => (string) $a['detail'], 'status' => (string) $a['status'], 'opened_at' => $ts($a['opened_at'])], $alerts),
    'trace_grades' => array_map(static fn (array $g): array => ['id' => (int) $g['trace_grade_id'], 'agent_run_id' => (int) $g['agent_run_id'], 'agent_name' => $g['agent_name'] ?? null,
        'agent_member_id' => $g['agent_member_id'] !== null ? (int) $g['agent_member_id'] : null,
        'passed' => $g['passed'] !== null ? (bool) $g['passed'] : null, 'score' => $g['score'] !== null ? (string) $g['score'] : null,
        'notes' => $g['grader_notes'] ?? null, 'graded_at' => $ts($g['graded_at'])], $grades),
]);
