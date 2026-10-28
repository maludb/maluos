<?php
declare(strict_types=1);

/**
 * Action `business_hours_save` — one weekday's opening hours (owner's decision 8, 2026-09-19).
 * Super-admin. An application that keeps SLA clocks reads the hours through the kernel.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/settings/hours.php';

require_super_admin();
require_post();
verify_csrf();

$pdo = db();
$weekday = request_integer('weekday');
$opens = request_string('opens');
$closes = request_string('closes');
$isOpen = request_bool('is_open');
$errors = [];
if ($weekday === null || $weekday < 1 || $weekday > 7) { $errors[] = 'A weekday is 1 (Monday) to 7 (Sunday).'; }
foreach ([$opens, $closes] as $t) { if (!preg_match('/^([01]\d|2[0-3]):[0-5]\d$/', $t)) { $errors[] = 'Times are written HH:MM.'; break; } }
if ($errors === [] && $closes <= $opens) { $errors[] = 'Closing must be after opening.'; }
if ($errors !== []) { settings_refuse($errors); }
$before = $pdo->query('SELECT is_open, opens, closes FROM business_hours WHERE weekday = ' . (int) $weekday)->fetch();
$pdo->prepare('UPDATE business_hours SET is_open = :o, opens = :a, closes = :b, updated_at = now() WHERE weekday = :w')
    ->execute(['o' => $isOpen ? 'true' : 'false', 'a' => $opens, 'b' => $closes, 'w' => $weekday]);
log_activity($pdo, 'business_hours.save', 'business_hours', $weekday, ['before' => $before ?: null, 'after' => ['is_open' => $isOpen, 'opens' => $opens, 'closes' => $closes]]);
emit_action_status(true, ['did' => 'Saved the hours for weekday ' . $weekday, 'refresh' => 'settingsChanged']);
header('HX-Push-Url: /settings/business');
