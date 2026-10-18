<?php
declare(strict_types=1);

/** Settings query functions (all owner-scoped to the signed-in member). PDO first. */

function update_profile(PDO $pdo, int $memberId, string $displayName, string $timezone, ?string $bio,
                        ?string $organization, ?string $jobTitle = null, ?string $phone = null): array
{
    // job_title and phone are part of the business profile action (manifest: profile_update);
    // passing null leaves whatever is stored, so the fork's own form keeps working unchanged.
    $st = $pdo->prepare(<<<'SQL'
        UPDATE members
           SET display_name = :n, timezone = :tz, bio = :bio, organization = :org,
               job_title = COALESCE(:job, job_title), phone = COALESCE(:phone, phone)
        WHERE id = :id RETURNING *
    SQL);
    $st->execute(['n' => $displayName, 'tz' => $timezone, 'bio' => $bio ?: null,
                  'org' => $organization ?: null, 'job' => $jobTitle, 'phone' => $phone, 'id' => $memberId]);
    return $st->fetch();
}

function update_notifications(PDO $pdo, int $memberId, bool $reply, bool $event, bool $exam, bool $digest): array
{
    $st = $pdo->prepare(<<<'SQL'
        UPDATE members SET notify_reply = :r, notify_event = :e, notify_exam = :x, notify_digest = :d
        WHERE id = :id RETURNING *
    SQL);
    $st->execute(['r' => $reply ? 1 : 0, 'e' => $event ? 1 : 0, 'x' => $exam ? 1 : 0, 'd' => $digest ? 1 : 0, 'id' => $memberId]);
    return $st->fetch();
}

// ---- MCP access tokens ----------------------------------------------------
function list_mcp_tokens(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare('SELECT id, label, last_used_at, created_at FROM mcp_access_tokens WHERE member_id = :m AND revoked_at IS NULL ORDER BY created_at DESC');
    $st->execute(['m' => $memberId]);
    return $st->fetchAll();
}

/** @return array{raw:string,id:int} */
function create_mcp_token(PDO $pdo, int $memberId, string $label): array
{
    $raw = 'mcp_' . bin2hex(random_bytes(24));
    $st = $pdo->prepare('INSERT INTO mcp_access_tokens (member_id, label, token_hash) VALUES (:m, :l, :h) RETURNING id');
    $st->execute(['m' => $memberId, 'l' => $label, 'h' => hash('sha256', $raw)]);
    return ['raw' => $raw, 'id' => (int) $st->fetchColumn()];
}

function revoke_mcp_token(PDO $pdo, int $id, int $memberId): bool
{
    $st = $pdo->prepare('UPDATE mcp_access_tokens SET revoked_at = now() WHERE id = :id AND member_id = :m AND revoked_at IS NULL');
    $st->execute(['id' => $id, 'm' => $memberId]);
    return $st->rowCount() === 1;
}

// ---- TOTP enrollment ------------------------------------------------------
/** Persist a confirmed TOTP secret + 10 recovery codes. @return string[] plain recovery codes (shown once) */
function enable_totp(PDO $pdo, int $memberId, string $secret): array
{
    $pdo->beginTransaction();
    try {
        $pdo->prepare('UPDATE members SET totp_secret = :s, totp_enabled_at = now(), totp_last_timestep = NULL WHERE id = :id')
            ->execute(['s' => encrypt_secret($secret), 'id' => $memberId]);
        $pdo->prepare('DELETE FROM totp_recovery_codes WHERE member_id = :id')->execute(['id' => $memberId]);
        $codes = [];
        $ins = $pdo->prepare('INSERT INTO totp_recovery_codes (member_id, code_hash) VALUES (:m, :h)');
        for ($i = 0; $i < 10; $i++) {
            $code = substr(bin2hex(random_bytes(5)), 0, 4) . '-' . substr(bin2hex(random_bytes(5)), 0, 4);
            $codes[] = $code;
            $ins->execute(['m' => $memberId, 'h' => password_hash($code, PASSWORD_BCRYPT, ['cost' => PASSWORD_COST])]);
        }
        $pdo->commit();
        return $codes;
    } catch (Throwable $e) {
        if ($pdo->inTransaction()) { $pdo->rollBack(); }
        throw $e;
    }
}

function disable_totp(PDO $pdo, int $memberId): void
{
    $pdo->beginTransaction();
    try {
        $pdo->prepare('UPDATE members SET totp_secret = NULL, totp_enabled_at = NULL, totp_last_timestep = NULL WHERE id = :id')->execute(['id' => $memberId]);
        $pdo->prepare('DELETE FROM totp_recovery_codes WHERE member_id = :id')->execute(['id' => $memberId]);
        $pdo->commit();
    } catch (Throwable $e) {
        if ($pdo->inTransaction()) { $pdo->rollBack(); }
        throw $e;
    }
}

/** Render one settings section's HTML (used by the page + every settings write endpoint). */
function settings_section_html(PDO $pdo, int $memberId, string $section, array $extra = []): string
{
    $m = find_member_by_id($pdo, $memberId);
    switch ($section) {
        case 'notifications':
            return view('settings/partials/notifications.php', ['m' => $m] + $extra);
        case 'security':
            return view('settings/partials/security.php', [
                'enabled' => $m['totp_enabled_at'] !== null,
            ] + $extra);
        case 'tokens':
            return view('settings/partials/tokens.php', [
                'tokens' => list_mcp_tokens($pdo, $memberId),
                'recordsUrl' => app_url('/mcp/records'),
                'activityUrl' => app_url('/mcp/activity'),
            ] + $extra);
        case 'profile':
        default:
            return view('settings/partials/profile.php', ['m' => $m, 'timezones' => timezone_identifiers_list()] + $extra);
    }
}
