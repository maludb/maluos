<?php
declare(strict_types=1);

/**
 * GET /api/v1/me — the signed-in member: id, name, title, kind, departments (and, for an
 * agent, its detail) — the same shape /api/v1/members/{id} returns for any other member,
 * reusing member_node_detail() so the two can never disagree (build spec:
 * docs/build-specs/public-api-org-graph.md).
 */
require_once dirname(__DIR__, 3) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/orgchart/queries.php';

api_cors();
api_require_get();

$member = api_authenticate();
$pdo = db();

$detail = member_node_detail($pdo, (int) $member['id']);
if ($detail === null) {
    // The caller authenticated as this member but the team-directory view will not return
    // them (e.g. suspended mid-session) — still a 404, never a 403 or a 500.
    log_activity($pdo, 'api.me.read', 'member', (int) $member['id'], ['source' => 'api', 'after' => ['found' => false]]);
    api_error('not_found', 'Not found.', 404);
}

log_activity($pdo, 'api.me.read', 'member', (int) $member['id'], ['source' => 'api']);

api_json($detail);
