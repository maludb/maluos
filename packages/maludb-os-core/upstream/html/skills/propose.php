<?php
declare(strict_types=1);

/**
 * Action `skill_propose` — a skill an agent wrote during a run becomes a proposal. Not reachable
 * from a browser or by an agent: the agent runner posts here after a run, from localhost, with
 * RUNNER_KEY (the same machine-to-machine door as agents/run-callback.php), after collecting the
 * folder from the agent's outbox.
 *
 * The bundle is scanned (features/skills/scan.php), ingested into MaluDB and IMMEDIATELY DISABLED,
 * so it exists with its hash and lineage but no agent can receive it until a person approves it.
 * MaluDB's ingest has no "disabled" option, so there is a moment in which the new row is enabled;
 * if it cannot then be disabled it is deleted — a skill nobody reviewed must never stay live.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
require_once dirname(__DIR__, 2) . '/app/features/skills/maludb.php';
require_once dirname(__DIR__, 2) . '/app/features/skills/scan.php';
require_once dirname(__DIR__, 2) . '/app/features/skills/queries.php';
agents_require_files();

require_post();
$presented = (string) ($_SERVER['HTTP_X_RUNNER_KEY'] ?? '');
if (!in_array($_SERVER['REMOTE_ADDR'] ?? '', ['127.0.0.1', '::1'], true) || $presented === '' || !hash_equals(runner_key(), $presented)) {
    http_response_code(403);
    exit('Forbidden.');
}
header('Content-Type: application/json');
$answer = static function (int $status, array $body): never {
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
};

$pdo = db();
$run = ($runId = request_integer('agent_run')) !== null ? find_agent_run($pdo, $runId) : null;
if ($run === null || $run['agent_member_id'] === null) {
    $answer(404, ['ok' => false, 'error' => 'No such agent run.']);
}
$agentId = (int) $run['agent_member_id'];
$name = trim(request_string('skill_name'));
$decoded = json_decode(request_string('files'), true);
$files = [];
foreach (is_array($decoded) ? $decoded : [] as $f) {
    $content = base64_decode((string) ($f['content_base64'] ?? ''), true);
    if (!is_array($f) || !is_string($f['relative_path'] ?? null) || $content === false) {
        $answer(422, ['ok' => false, 'error' => 'Every file needs relative_path and content_base64.']);
    }
    $files[] = ['relative_path' => $f['relative_path'], 'content' => $content];
}

$logAs = ['actor_member_id' => $agentId, 'source' => 'agent', 'agent_run_id' => (int) $run['id'], 'request_id' => (string) $run['request_id']];
[$refusal, $findings] = scan_skill_bundle($name, $files);
if ($refusal !== null) {
    log_activity($pdo, 'skill.propose_refused', 'member', $agentId, $logAs + ['after' => ['skill_name' => $name, 'reason' => $refusal]]);
    $answer(422, ['ok' => false, 'refused' => true, 'error' => $refusal]);
}
$markdown = '';
foreach ($files as $f) {
    if ($f['relative_path'] === 'SKILL.md') {
        $markdown = $f['content'];
    }
}
$front = skill_frontmatter($markdown);
$description = (string) ($front['description'] ?? '');
if ($description === '') {
    $answer(422, ['ok' => false, 'refused' => true, 'error' => 'SKILL.md needs a frontmatter description — it is how an agent decides to use the skill.']);
}

// What it would replace, for the reviewer's diff — read BEFORE the ingest, while "newest enabled" still means the old one.
[$parent] = maludb_skill_resolve($name);
$parentMarkdown = $parent !== null ? maludb_skill_file_text((int) $parent['id'], 'SKILL.md') : null;

$kind = skill_kind_from_frontmatter(skill_frontmatter($markdown));
[$ingested, $error] = maludb_skill_ingest($name, $description, $markdown, $files, $kind);
if ($error !== null) {
    $answer(424, ['ok' => false, 'error' => $error]);
}
if ($ingested['reused']) {
    // Byte-identical to a bundle MaluDB already holds. NEVER disable it: it may be the live skill.
    $existing = find_skill_proposal_by_hash($pdo, $name, $ingested['bundle_hash']);
    $answer(200, ['ok' => true, 'unchanged' => true, 'skill_proposal_id' => $existing !== null ? (int) $existing['id'] : null]);
}
$error = maludb_skill_set_enabled($ingested['skill_id'], false);
if ($error !== null) {
    maludb_request('DELETE', '/v1/skills/' . $ingested['skill_id']);
    error_log('skill proposal ' . $name . ': could not disable the new bundle, deleted it instead: ' . $error);
    $answer(424, ['ok' => false, 'error' => 'The skill could not be held for review, so it was not kept.']);
}

$proposalId = create_skill_proposal($pdo, [
    'agent_member_id' => $agentId, 'agent_run_id' => (int) $run['id'], 'skill_name' => $name,
    'bundle_hash' => $ingested['bundle_hash'], 'parent_bundle_hash' => $parent['bundle_hash'] ?? null,
    'maludb_skill_id' => $ingested['skill_id'], 'file_count' => count($files), 'scan_findings' => $findings,
    'skill_markdown' => $markdown, 'parent_markdown' => $parentMarkdown,
]);
log_activity($pdo, 'skill.propose', 'skill_proposal', $proposalId, $logAs + ['after' => [
    'skill_name' => $name, 'bundle_hash' => $ingested['bundle_hash'], 'is_change' => $parent !== null,
    'files' => count($files), 'findings' => count($findings),
]]);
$answer(201, ['ok' => true, 'skill_proposal_id' => $proposalId, 'findings' => count($findings)]);
