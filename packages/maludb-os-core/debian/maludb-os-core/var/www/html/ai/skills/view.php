<?php
declare(strict_types=1);

/**
 * Screen `skills-library-view` — one skill: its versions, the chosen version's SKILL.md and reference
 * files, and who holds it. `?name=` (and `&version=<id>` for an older one). Also the edit form's data.
 * Gate: super. JSON only (React).
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/skills/library.php';
require_once dirname(__DIR__, 3) . '/app/features/skills/present.php';

require_super_admin();
$pdo = db();
$name = request_string('name');
try {
    $skill = $name === '' ? null : skill_library_get($pdo, $name, request_integer('version'));
} catch (RuntimeException $ex) {
    json_error('unavailable', $ex->getMessage(), 503);
}
if ($skill === null) {
    json_error('not_found', 'Skill not found.', 404);
}
log_screen_view($pdo, 'skills-library-view');
respond_screen([
    'skill' => present_library_skill_detail($skill),
    'can' => ['edit' => is_super_admin()],
]);
