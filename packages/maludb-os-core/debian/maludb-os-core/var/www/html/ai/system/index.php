<?php
declare(strict_types=1);

/**
 * Screen `system` (GET /ai/system/) — what the Sysadmin sees on this server (db/145): the health probes,
 * the open events from the logs and the kernel's guardrails (redacted samples only), and its recent
 * decisions — in shadow, what it would have done. The super-admin, or an admin of IT. JSON only.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';

require_login();
if (!is_super_admin() && !is_business_admin()) { json_error('forbidden', 'The system view is for the super-admin and IT admins.', 403); }
$pdo = db();
log_screen_view($pdo, 'system');
$status = request_string('status', 'open');
$where = $status === 'all' ? '' : ($status === 'muted' ? "WHERE status = 'muted'" : "WHERE status IN ('open', 'acknowledged')");
$events = $pdo->query("SELECT * FROM mcp_system_events {$where} ORDER BY severity DESC NULLS LAST, last_seen DESC LIMIT 200")->fetchAll();
$probes = $pdo->query('SELECT * FROM mcp_system_probes ORDER BY CASE status WHEN \'failed\' THEN 0 WHEN \'warning\' THEN 1 ELSE 2 END, probe')->fetchAll();
$decisions = $pdo->query("SELECT d.* FROM mcp_system_one_decisions d WHERE d.playbook IN ('health', 'logs_and_guardrails') AND d.decision <> 'record'
                           ORDER BY d.created_at DESC LIMIT 50")->fetchAll();
$agents = $pdo->query("SELECT DISTINCT d.agent_member_id, d.agent_name, (SELECT d2.mode FROM mcp_system_one_decisions d2 WHERE d2.agent_member_id = d.agent_member_id ORDER BY d2.created_at DESC LIMIT 1) AS mode
                         FROM mcp_system_one_decisions d WHERE d.playbook IN ('health', 'logs_and_guardrails')")->fetchAll();
$ts = static fn ($v) => json_ts($v ?? null);
respond_screen([
    'filters' => ['status' => $status],
    'agents' => array_map(static fn (array $a): array => ['id' => (int) $a['agent_member_id'], 'name' => (string) $a['agent_name'], 'mode' => (string) ($a['mode'] ?? 'shadow')], $agents),
    'probes' => array_map(static fn (array $p): array => ['probe' => (string) $p['probe'], 'status' => (string) $p['status'], 'detail' => (string) $p['detail'],
        'checked_at' => $ts($p['checked_at']), 'changed_at' => $ts($p['changed_at'])], $probes),
    'events' => array_map(static fn (array $e): array => ['id' => (int) $e['system_event_id'], 'source' => (string) $e['source'], 'sample' => (string) $e['sample'],
        'category' => $e['category'], 'severity' => $e['severity'] !== null ? (int) $e['severity'] : null, 'occurrences' => (int) $e['occurrences'],
        'first_seen' => $ts($e['first_seen']), 'last_seen' => $ts($e['last_seen']), 'status' => (string) $e['status'],
        'status_by_name' => $e['status_by_name'] ?? null, 'note' => $e['note'] ?? null], $events),
    'decisions' => array_map(static fn (array $d): array => ['id' => (int) $d['decision_id'], 'agent_name' => (string) $d['agent_name'], 'playbook' => (string) $d['playbook'],
        'subject_kind' => (string) $d['subject_kind'], 'subject_id' => $d['subject_id'] !== null ? (int) $d['subject_id'] : null,
        'subject' => (string) ($d['subject_label'] ?? ''), 'decision' => (string) $d['decision'], 'mode' => (string) $d['mode'], 'acted' => (bool) $d['acted'],
        'note' => $d['note'] ?? null, 'at' => $ts($d['created_at'])], $decisions),
    'can' => ['act' => true],
]);
