<?php
declare(strict_types=1);

use OTPHP\TOTP;

/**
 * TOTP (authenticator-app 2FA). Enrollment lives on the settings screen; this file
 * covers the login-challenge verification path and recovery codes.
 */

const TOTP_PERIOD = 30;
const TOTP_DIGITS = 6;

/** Build a TOTP instance from a decrypted secret. */
function totp_from_secret(string $secret): TOTP
{
    $totp = TOTP::createFromSecret($secret);
    $totp->setPeriod(TOTP_PERIOD);
    $totp->setDigits(TOTP_DIGITS);
    return $totp;
}

/**
 * Verify a code against the member's encrypted secret with a ±1 timestep window and a
 * monotonic replay guard: any timestep <= totp_last_timestep is rejected, and the
 * accepted timestep is persisted. Returns true on success.
 */
function verify_totp_code(PDO $pdo, array $member, string $code): bool
{
    $code = preg_replace('/\D/', '', $code);
    if ($code === '' || $member['totp_secret'] === null) {
        return false;
    }
    $totp = totp_from_secret(decrypt_secret($member['totp_secret']));
    $now = time();
    $currentStep = intdiv($now, TOTP_PERIOD);
    $last = $member['totp_last_timestep'] !== null ? (int) $member['totp_last_timestep'] : -1;

    foreach ([-1, 0, 1] as $offset) {
        $step = $currentStep + $offset;
        if ($step <= $last) {
            continue;   // replay guard
        }
        if (hash_equals($totp->at($step * TOTP_PERIOD), $code)) {
            $pdo->prepare('UPDATE members SET totp_last_timestep = :s WHERE id = :id')
                ->execute(['s' => $step, 'id' => (int) $member['id']]);
            return true;
        }
    }
    return false;
}

/** Verify and consume a single-use recovery code. Returns true on success. */
function verify_recovery_code(PDO $pdo, int $memberId, string $code): bool
{
    $code = trim($code);
    if ($code === '') {
        return false;
    }
    $st = $pdo->prepare('SELECT id, code_hash FROM totp_recovery_codes WHERE member_id = :m AND used_at IS NULL');
    $st->execute(['m' => $memberId]);
    foreach ($st->fetchAll() as $row) {
        if (password_verify($code, $row['code_hash'])) {
            $pdo->prepare('UPDATE totp_recovery_codes SET used_at = now() WHERE id = :id')
                ->execute(['id' => (int) $row['id']]);
            return true;
        }
    }
    return false;
}

/** Count a member's remaining (unused) recovery codes. */
function remaining_recovery_codes(PDO $pdo, int $memberId): int
{
    $st = $pdo->prepare('SELECT count(*) FROM totp_recovery_codes WHERE member_id = :m AND used_at IS NULL');
    $st->execute(['m' => $memberId]);
    return (int) $st->fetchColumn();
}
