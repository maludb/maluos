<?php
declare(strict_types=1);

/**
 * GET /api/v1/estate/apps/job?id=<job> — the state of a registration this node started (db/194;
 * app/features/applications/remote_install.php). Bearer = its node token; the door and the internal port only.
 * Answers {"state": "running"|"done"|"failed", "exit": n|null, "output": "…", "result": {"application_token": "…"}}:
 * the result once, with the first answer after the run ended.
 */
require_once dirname(__DIR__, 5) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 5) . '/app/features/estate/nodes.php';
require_once dirname(__DIR__, 5) . '/app/features/applications/remote_install.php';

$auth = node_authenticate();
$dir = app_install_job_dir((int) $auth['node']['id'], (string) ($_GET['id'] ?? ''));
if ($dir === null) { api_error('not_found', 'No such registration for this server.', 404); }
api_json(app_install_job($dir));
