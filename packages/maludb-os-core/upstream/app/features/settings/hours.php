<?php
declare(strict_types=1);

/**
 * Business hours — one row per weekday (db/109, owner's decision 8 of 2026-09-19). A business
 * setting since the kernel cut of 2026-09-22: the Helpdesk that used them for SLA clocks is an
 * application now, and reads them through the kernel when it needs them.
 */

/** weekday (1 = Monday … 7 = Sunday) → ['is_open' => bool, 'opens' => 'HH:MM:SS', 'closes' => 'HH:MM:SS'] */
function find_business_hours(PDO $pdo): array
{
    $hours = [];
    foreach ($pdo->query('SELECT weekday, is_open, opens, closes FROM mcp_business_hours ORDER BY weekday')->fetchAll() as $h) {
        $hours[(int) $h['weekday']] = ['is_open' => (bool) $h['is_open'], 'opens' => (string) $h['opens'], 'closes' => (string) $h['closes']];
    }
    return $hours;
}

function present_business_hours(array $hours): array
{
    $days = [1 => 'Monday', 2 => 'Tuesday', 3 => 'Wednesday', 4 => 'Thursday', 5 => 'Friday', 6 => 'Saturday', 7 => 'Sunday'];
    $out = [];
    foreach ($days as $d => $name) {
        $out[] = ['weekday' => $d, 'name' => $name, 'is_open' => (bool) ($hours[$d]['is_open'] ?? false),
            'opens' => substr((string) ($hours[$d]['opens'] ?? '09:00'), 0, 5), 'closes' => substr((string) ($hours[$d]['closes'] ?? '17:00'), 0, 5)];
    }
    return $out;
}

/** A refusal in the handler's own words (no template: the handler was born after the cut-over). */
function settings_refuse(array $errors, int $status = 422): never
{
    emit_action_status(false, ['errors' => $errors]);
    if ($status === 422) {
        respond_invalid($errors);
    }
    json_error($status === 404 ? 'not_found' : ($status === 409 ? 'conflict' : 'forbidden'), (string) $errors[0], $status);
}
