<?php
declare(strict_types=1);

/**
 * GET /api/v1/graph?focus=<kind>:<id> — the Agent View payload centred on a record instead of
 * a person (build spec: docs/build-specs/agent-view-focus-graph.md). Kinds: department, agent,
 * project, location, organization. Everything it returns is what the focus record's own screen
 * already shows this caller — app/features/orgchart/focus.php holds that rule.
 *
 * Session-only, like /api/v1/session (owner's decision, 2026-09-19): no bearer path and no
 * CORS headers. Its only caller is this app's own Next.js server, forwarding a signed-in
 * person's cookie. If it is ever made public, the token path logs `api.graph.read` instead.
 *
 * Logged as ONE screen view per open, like every other screen (owner's decision): screen
 * `agent-view-focus`, entity = the focus record. The rule log_screen_view() applies in JSON
 * mode is applied here — a read counts only when the Next.js server marks a real page render
 * (X-Screen-View: 1), which is also what makes the quiet cookie work. It is written out
 * rather than called because a screen view carries no entity and this one must.
 */
require_once dirname(__DIR__, 3) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/orgchart/focus.php';

api_require_get();

$member = is_logged_in() ? current_member() : null;
if ($member === null || ($member['status'] ?? '') !== 'active') {
    api_error('unauthorized', 'Sign in to open this view.', 401);
}

if (!preg_match('/^([a-z]+):([1-9]\d{0,17})$/', request_string('focus'), $m)
    || !in_array($m[1], FOCUS_KINDS, true)) {
    api_error('bad_focus', 'focus must be <kind>:<id>, where kind is one of: '
        . implode(', ', FOCUS_KINDS) . '.', 400);
}
[$kind, $id] = [$m[1], (int) $m[2]];

$pdo = db();
$graph = focus_graph($pdo, $kind, $id);
if ($graph === null) {
    // Does not exist, or this caller may not see it — indistinguishable on purpose.
    api_error('not_found', 'Nothing to show here.', 404);
}

if (($_SERVER['HTTP_X_SCREEN_VIEW'] ?? '') === '1') {
    log_activity($pdo, 'screen.view', FOCUS_ENTITY[$kind], $id, ['screen' => 'agent-view-focus']);
}

api_json($graph);
