<?php
declare(strict_types=1);

/** Action `eval_alert_acknowledge` — mod:evals or the agent's manager; never an agent. (Alerts are raised by the eval runner, which is not built — none exists yet.) */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';

require_post();
verify_csrf();

$pdo = db();
$st = $pdo->prepare('SELECT * FROM mcp_eval_alerts WHERE eval_alert_id = :id');
$st->execute(['id' => request_integer('eval_alert') ?? 0]);
$alert = $st->fetch() ?: null;
aiops_require_evals($pdo, $alert !== null && $alert['agent_member_id'] !== null ? (int) $alert['agent_member_id'] : null, true);
if ($alert === null) { aiops_refuse(['Alert not found.'], 404); }
if ($alert['status'] === 'resolved') { aiops_refuse(['It is already resolved.'], 409); }
if ($alert['status'] === 'acknowledged') { aiops_refuse(['It is already acknowledged.'], 409); }
$note = mb_substr(trim(request_string('note')), 0, 1000) ?: null;
$pdo->prepare("UPDATE eval_alerts SET status = 'acknowledged', acknowledged_by = :by, acknowledged_at = now(), resolution = coalesce(:n, resolution), updated_at = now() WHERE id = :id")
    ->execute(['by' => (int) current_member_id(), 'n' => $note, 'id' => (int) $alert['eval_alert_id']]);
log_activity($pdo, 'eval_alert.acknowledge', 'eval_alert', (int) $alert['eval_alert_id'], ['before' => ['status' => $alert['status']], 'after' => ['status' => 'acknowledged', 'note' => $note]]);
emit_action_status(true, ['did' => 'Acknowledged the alert on ' . $alert['eval_set_name'], 'refresh' => 'aiopsChanged']);
header('HX-Push-Url: /ai/evals/alerts/' . (int) $alert['eval_alert_id']);
