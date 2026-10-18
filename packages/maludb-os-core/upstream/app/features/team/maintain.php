<?php
declare(strict_types=1);

/**
 * Maintaining a person from the operating system (2026-09-26): their details, and suspending or
 * reinstating them. A suspended member is signed out of the kernel on their next request
 * (/api/v1/session.php answers them as signed out; login refuses them), holds nothing on any
 * application (app_member_grants() needs `active`), and every application's mirror hears it from the
 * change feed within a minute. Agents are maintained in Agent HR, never here.
 */

const MEMBER_DETAIL_FIELDS = ['display_name', 'job_title', 'phone', 'timezone'];

/** [fields, errors] for member_update — only what was sent changes. */
function member_detail_fields_from_request(): array
{
    $fields = [];
    foreach (MEMBER_DETAIL_FIELDS as $k) {
        if (array_key_exists($k, $_POST)) {
            $fields[$k] = trim(request_string($k));
        }
    }
    $errors = [];
    if (array_key_exists('display_name', $fields) && ($fields['display_name'] === '' || mb_strlen($fields['display_name']) > 120)) {
        $errors[] = 'A name is needed (up to 120 characters).';
    }
    if (array_key_exists('timezone', $fields) && !in_array($fields['timezone'], timezone_identifiers_list(), true)) {
        $errors[] = 'That is not a time zone — use a name like America/New_York.';
    }
    foreach (['job_title' => 120, 'phone' => 40] as $k => $max) {
        if (array_key_exists($k, $fields)) {
            if (mb_strlen($fields[$k]) > $max) {
                $errors[] = ucfirst(str_replace('_', ' ', $k)) . ' is up to ' . $max . ' characters.';
            }
            $fields[$k] = $fields[$k] === '' ? null : $fields[$k];
        }
    }
    if ($fields === [] && $errors === []) {
        $errors[] = 'Nothing to change: send display_name, job_title, phone or timezone.';
    }
    return [$fields, $errors];
}

function update_member_details(PDO $pdo, int $memberId, array $fields): void
{
    $set = [];
    $args = ['id' => $memberId];
    foreach ($fields as $k => $v) {
        $set[] = "{$k} = :{$k}";      // $k is from MEMBER_DETAIL_FIELDS only
        $args[$k] = $v;
    }
    $pdo->prepare('UPDATE members SET ' . implode(', ', $set) . ', updated_at = now() WHERE id = :id')->execute($args);
}

/** Set a person's status; the row as it was, or null when it was not in $from. */
function set_member_status(PDO $pdo, int $memberId, string $from, string $to): bool
{
    $st = $pdo->prepare('UPDATE members SET status = :to, updated_at = now() WHERE id = :id AND status = :from');
    $st->execute(['to' => $to, 'from' => $from, 'id' => $memberId]);
    return $st->rowCount() === 1;
}

function other_active_super_admins(PDO $pdo, int $memberId): int
{
    $st = $pdo->prepare("SELECT count(*) FROM members WHERE business_role = 'super_admin' AND status = 'active' AND id <> :id");
    $st->execute(['id' => $memberId]);
    return (int) $st->fetchColumn();
}
