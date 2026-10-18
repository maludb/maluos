<?php
declare(strict_types=1);

/** Screen `skills-library` — AI Ops → Skills: every skill in the library as a card. Gate: super. JSON only (React). */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/skills/library.php';
require_once dirname(__DIR__, 3) . '/app/features/skills/present.php';

require_super_admin();
$pdo = db();
log_screen_view($pdo, 'skills-library');
try {
    $skills = skill_library($pdo);
} catch (RuntimeException $ex) {
    json_error('unavailable', $ex->getMessage(), 503);
}
respond_screen([
    'skills' => array_map('present_library_skill', $skills),
    'can' => ['edit' => is_super_admin()],
]);
