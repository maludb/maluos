<?php
declare(strict_types=1);

/**
 * GET /api/v1/health — liveness. No auth, discloses nothing about the business
 * (build spec: docs/build-specs/public-api-org-graph.md).
 */
require_once dirname(__DIR__, 3) . '/app/api/bootstrap.php';

api_cors();
api_require_get();

log_activity(db(), 'api.health.read', null, null, ['source' => 'api']);

api_json(['status' => 'ok', 'time' => gmdate('c')]);
