<?php
declare(strict_types=1);

/**
 * POST /api/v1/runs/facts.php — the run-facts call (A7 (b)). An application's read server
 * presents the token a caller gave it (body `token`) with its own application token, and learns
 * what only the kernel knows: is this an agent, which run, is the run an evaluation, and which
 * tools that agent holds on THIS application's endpoints — so the application fails closed on a
 * run token without a copy of the kernel's grants. A person's token answers is_agent=false: a
 * person is never filtered. An invalid token answers valid=false (200): the application refuses. K38 (2026-10-10): an agent's run
 * also answers who it acts for (requested_by_member_id, requested_by_kind, requested_by_holds — run_facts_requester()).
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/api/directory.php';

directory_authenticate();
$pdo = db();
$app = directory_application();
if (directory_method() !== 'POST') {
    header('Allow: POST');
    api_error('method_not_allowed', 'POST the token in the body.', 405);
}
$body = directory_body();
$token = trim((string) ($body['token'] ?? ''));
if ($token === '') {
    api_error('invalid', 'token is the bearer the caller presented to you.', 422);
}
$verified = verify_token_signature($token);       // the signature alone: an application never holds the relay key
if ($verified === null) {
    api_json(['valid' => false, 'is_agent' => false, 'reason' => 'The token does not verify, or has expired.']);
}
[$memberId, $runId] = $verified;
$member = find_member_by_id($pdo, $memberId);
if ($member === null || $member['status'] !== 'active') {
    api_json(['valid' => false, 'is_agent' => false, 'reason' => 'The member is not active.']);
}
$out = ['valid' => true, 'member_id' => $memberId, 'member_name' => (string) $member['display_name'],
        'is_agent' => ($member['member_kind'] ?? 'human') === 'agent', 'run_id' => $runId, 'request_id' => null,
        'trigger' => null, 'is_eval' => false, 'run_status' => null, 'endpoints' => []];
if ($runId !== null) {
    $st = $pdo->prepare('SELECT request_id, trigger, status FROM agent_runs WHERE id = :r AND agent_member_id = :m');
    $st->execute(['r' => $runId, 'm' => $memberId]);
    $run = $st->fetch() ?: null;
    if ($run === null) {
        api_json(['valid' => false, 'is_agent' => true, 'reason' => 'No such run for that agent.']);
    }
    $out['request_id'] = (string) $run['request_id'];
    $out['trigger'] = (string) $run['trigger'];
    $out['is_eval'] = $run['trigger'] === 'eval';
    $out['run_status'] = (string) $run['status'];
}
if ($out['is_agent']) {
    $st = $pdo->prepare(<<<'SQL'
        SELECT e.id, e.name, e.url, e.mcp_surface_version,
               coalesce(jsonb_object_agg(g.tool_name, coalesce(g.constraints, '{}'::jsonb)) FILTER (WHERE g.tool_name IS NOT NULL), '{}'::jsonb) AS tools
          FROM application_endpoints e
          LEFT JOIN agent_tool_grants g ON g.application_endpoint_id = e.id AND g.agent_member_id = :m AND g.revoked_at IS NULL
         WHERE e.application_id = :a AND e.kind = 'mcp' AND e.agent_reachable AND e.status = 'active'
         GROUP BY e.id, e.name, e.url, e.mcp_surface_version ORDER BY e.id
    SQL);
    $st->execute(['m' => $memberId, 'a' => $app['id']]);
    foreach ($st->fetchAll() as $e) {
        $out['endpoints'][] = ['id' => (int) $e['id'], 'name' => (string) $e['name'], 'url' => (string) $e['url'],
            'mcp_surface_version' => $e['mcp_surface_version'] ?? null,
            'tools' => is_string($e['tools']) ? (json_decode($e['tools'], true) ?: (object) []) : ($e['tools'] ?: (object) [])];
    }
}
// What the caller holds on this application (db/141): its role, and on a scoped application every
// site or department with the role there — the same shape as the sign-on claims. An agent is granted
// per scope like a person; a caller holding nothing here answers capability null.
require_once dirname(__DIR__, 4) . '/app/features/applications/sso.php';
$holding = sso_member_holding($pdo, (int) $app['id'], $memberId);
$out['capability'] = $holding['capability'];
$out['role'] = $holding['role'];
$out['roles'] = $holding['roles'];     // db/145, additive
$out['rights'] = $holding['rights'];
$out['scopes'] = $holding['scopes'];
// K38 (2026-10-10): who the run acts for — a chat, manual or delegated run's requester and whether they hold this application; null
// otherwise. An application intersects the agent's access with that person's (the person never sees less than the agent would let them,
// the agent never reads more than the person may). Additive: an older application ignores the three keys.
$out += $out['is_agent'] && $runId !== null
    ? run_facts_requester($pdo, (int) $app['id'], (int) $runId, $memberId)
    : ['requested_by_member_id' => null, 'requested_by_kind' => null, 'requested_by_holds' => false];
api_json($out);
