<?php
declare(strict_types=1);

/**
 * Action `skill_save` — log `skill.save`. Gate: super; never an agent (an agent proposes a skill
 * instead — skill_propose, decided by a person).
 *
 * A new skill, or a new version of one: name, description, the instructions (the body of SKILL.md) and
 * any reference files (`files[i][path]`, `files[i][content]`, text only). A bundle is never edited in
 * place — a changed one becomes a new version in MaluDB with lineage, the previous versions kept; an
 * unchanged one changes nothing. The new version is enabled, so every agent holding the skill (unpinned)
 * gets it at its next run. It passes the same scan as an import or an agent's proposal.
 * Born after the cut-over: no template, so a refusal says its own words (respond_invalid).
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/skills/library.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$name = strtolower(trim(request_string('name')));
$files = [];
foreach (is_array($_POST['files'] ?? null) ? $_POST['files'] : [] as $f) {
    if (!is_array($f)) {
        continue;                                   // a path alone (the agents' door cannot send files)
    }
    $path = trim((string) ($f['path'] ?? ''));
    $content = str_replace("\r\n", "\n", (string) ($f['content'] ?? ''));
    if ($path === '' && trim($content) === '') {
        continue;                                   // an empty row of the form
    }
    $files[] = ['relative_path' => $path, 'content' => $content];
}

$existing = null;
try {
    $existing = skill_library_get($pdo, $name);
} catch (RuntimeException) {
    // MaluDB unreachable: the save below says so in its own words.
}

check_approval($pdo, 'skill_save', 'skill.save', ($existing === null ? 'Create skill ' : 'Save a new version of skill ') . $name,
    ['name' => $name, 'files' => count($files)], 'skill', null);

$kind = request_string('kind') === 'runbook' ? 'runbook' : 'skill';
[$ingested, $errors, $findings] = skill_library_save($pdo, $name, request_string('description'),
    str_replace("\r\n", "\n", (string) ($_POST['body'] ?? '')), $files, $kind);
if ($ingested === null) {
    emit_action_status(false, ['errors' => $errors]);
    respond_invalid($errors);
}

log_activity($pdo, 'skill.save', 'skill', (int) $ingested['skill_id'], [
    'before' => $existing === null ? null : ['version' => $existing['chosen']['version'] ?? null],
    'after' => ['skill_name' => $name, 'bundle_hash' => $ingested['bundle_hash'], 'files' => count($files) + 1,
                'reused' => (bool) $ingested['reused'], 'new' => $existing === null,
                'findings' => array_map(static fn (array $f): string => $f['kind'] . ' in ' . $f['file'], $findings)],
]);
$said = $ingested['reused'] ? 'Nothing changed in ' . $name
    : ($existing === null ? 'Created skill ' . $name : 'Saved a new version of ' . $name);
if ($findings !== []) {
    $said .= ' — the scan flagged ' . count($findings) . ' thing' . (count($findings) === 1 ? '' : 's') . ' to read (URLs, commands or instructions); the skill is saved';
}
emit_action_status(true, ['did' => $said, 'record_id' => (int) $ingested['skill_id'], 'refresh' => 'skillsChanged']);
header('HX-Push-Url: /ai/skills/' . rawurlencode($name));
