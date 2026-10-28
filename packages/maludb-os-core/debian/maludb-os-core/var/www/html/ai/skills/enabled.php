<?php
declare(strict_types=1);

/**
 * Action `skill_set_enabled` — log `skill.set_enabled`. Gate: super; never an agent.
 *
 * Enable or disable one version of a skill. Every agent holding the skill unpinned gets its newest
 * ENABLED version at its next run, so disabling the newest falls back to the one before, and disabling
 * every version takes the skill away from them (the answer says how many assignments that touches).
 * Born after the cut-over: no template, so a refusal says its own words (respond_invalid).
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/skills/library.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$name = request_string('name');
$versionId = request_integer('skill');
$enabled = request_string('enabled') === '1';
try {
    $skill = $name === '' || $versionId === null ? null : skill_library_get($pdo, $name, $versionId);
} catch (RuntimeException $ex) {
    emit_action_status(false, ['errors' => [$ex->getMessage()]]);
    respond_invalid([$ex->getMessage()]);
}
if ($skill === null || (int) $skill['chosen']['id'] !== $versionId) {
    emit_action_status(false, ['errors' => ['That version of the skill was not found.']]);
    respond_invalid(['That version of the skill was not found.']);
}

check_approval($pdo, 'skill_set_enabled', 'skill.set_enabled', ($enabled ? 'Enable ' : 'Disable ') . $name . ' ' . $skill['chosen']['version'],
    ['name' => $name, 'skill' => $versionId, 'enabled' => $enabled], 'skill', $versionId);

$error = maludb_skill_set_enabled($versionId, $enabled);
if ($error !== null) {
    emit_action_status(false, ['errors' => [$error]]);
    respond_invalid([$error]);
}
$stillEnabled = count(array_filter($skill['versions'], static fn (array $v): bool
    => (int) $v['id'] === $versionId ? $enabled : !empty($v['enabled'])));
log_activity($pdo, 'skill.set_enabled', 'skill', $versionId, [
    'before' => ['enabled' => !empty($skill['chosen']['enabled'])],
    'after' => ['skill_name' => $name, 'version' => $skill['chosen']['version'], 'enabled' => $enabled, 'enabled_versions' => $stillEnabled],
]);
$held = count($skill['assignments']);
$said = ($enabled ? 'Enabled ' : 'Disabled ') . $name . ' ' . $skill['chosen']['version'];
if (!$enabled && $stillEnabled === 0 && $held > 0) {
    $said .= ' — no version is enabled now, so the ' . $held . ' assignment' . ($held === 1 ? '' : 's') . ' holding it give nothing until one is';
}
emit_action_status(true, ['did' => $said, 'refresh' => 'skillsChanged']);
