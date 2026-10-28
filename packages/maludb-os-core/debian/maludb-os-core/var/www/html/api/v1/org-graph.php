<?php
declare(strict_types=1);

/**
 * GET /api/v1/org-graph — the whole AI Agent View payload for the signed-in caller: the
 * constellation and the left panel in one call, so the counts can never disagree with the
 * graph (build spec: docs/build-specs/public-api-org-graph.md). v1 takes one optional
 * parameter, include_retired (default false); no root parameter — the centre is the caller.
 */
require_once dirname(__DIR__, 3) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/orgchart/queries.php';

api_cors();
api_require_get();

$member = api_authenticate();
$pdo = db();

$includeRetired = request_bool('include_retired');

$graph = org_graph($pdo, (int) $member['id'], $includeRetired);

log_activity($pdo, 'api.org_graph.read', 'member', (int) $member['id'], [
    'source' => 'api',
    'after'  => ['include_retired' => $includeRetired],
]);

api_json($graph);
