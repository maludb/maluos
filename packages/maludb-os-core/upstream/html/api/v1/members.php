<?php
declare(strict_types=1);

/**
 * GET /api/v1/members/{id} — one node's detail, for "select a node to explore" (build spec:
 * docs/build-specs/public-api-org-graph.md). 404 when the member does not exist or the
 * caller cannot see them — never 403, and the same body as any other 404, so the API is not
 * an existence oracle the UI is not.
 *
 * Substitution (escalated to the spec's Open Questions): the spec claims "the installed
 * rewrite rules already map a trailing numeric segment ... no Apache change is needed —
 * verified". Re-verified here and it is not true for this path: none of the five installed
 * RewriteRules match /api/v1/members/{id} (the view.php-guarded rule needs a view.php that
 * doesn't exist here, and the two fallback rules test for members/{id}.php and
 * members/{id}/index.php, neither of which exist either), so Apache 404s the request before
 * PHP ever runs — confirmed against the access log. Out of this slice's scope is any Apache
 * change, so the canonical call is **`/api/v1/members.php?id={id}`** (also reachable as
 * `/api/v1/members?id={id}` via the existing generic rule), the same query-string
 * substitution the bookkeeping-ledger slice used for its own uncovered path
 * (`/books/banks/{id}/import` → `?bank_account={id}`, accepted in that spec's review).
 * api_path_id() still reads PATH_INFO/the trailing segment too, for free, in case a future
 * Apache change adds the missing rule.
 */
require_once dirname(__DIR__, 3) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/orgchart/queries.php';

api_cors();
api_require_get();

$member = api_authenticate();
$pdo = db();

$id = api_path_id();
if ($id === null) {
    api_error('bad_request', 'A member id is required.', 400);
}

$detail = member_node_detail($pdo, $id);
if ($detail === null) {
    log_activity($pdo, 'api.members.read', 'member', $id, ['source' => 'api', 'after' => ['found' => false]]);
    api_error('not_found', 'Not found.', 404);
}

log_activity($pdo, 'api.members.read', 'member', $id, ['source' => 'api']);

api_json($detail);
