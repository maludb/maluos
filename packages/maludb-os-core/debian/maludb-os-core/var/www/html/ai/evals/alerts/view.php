<?php
declare(strict_types=1);

/** Screen `eval-alert-view` — one alert: scores against baseline, the run behind it, what was done. */
require_once dirname(__DIR__, 4) . '/app/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 4) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 4) . '/app/features/aiops/present.php';

require_insider();
if (is_agent_member()) { deny('Evals are people\'s work — an agent cannot open them.'); }

$pdo = db();
$st = $pdo->prepare('SELECT a.*, (SELECT d.display_name FROM mcp_team_directory d WHERE d.member_id = a.acknowledged_by) AS acknowledged_by_name,
                            (SELECT d.member_kind FROM mcp_team_directory d WHERE d.member_id = a.acknowledged_by) AS acknowledged_by_kind
                       FROM mcp_eval_alerts a WHERE a.eval_alert_id = :id');
$st->execute(['id' => request_integer('id') ?? 0]);
if (($alert = $st->fetch()) === false) { http_response_code(404); exit('Alert not found.'); }
log_screen_view($pdo, 'eval-alert-view');
respond_screen(['alert' => present_eval_alert($alert), 'can' => ['act' => has_module_grant('evals') || aiops_can_see_agent($pdo, $alert['agent_member_id'] !== null ? (int) $alert['agent_member_id'] : null)]]);
