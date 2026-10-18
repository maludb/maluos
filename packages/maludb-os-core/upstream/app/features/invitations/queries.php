<?php
declare(strict_types=1);

/**
 * Invitation query functions (organizer Invitations screen). PDO-first, no request/
 * response awareness. Invite-only registration depends on these (auth.php reads them
 * on the registration path). Status is derived, not stored.
 */

const INVITE_TTL_DAYS = 7;

/** Pending invitations first, then recently accepted/revoked. */
function find_invitations(PDO $pdo, int $limit = 100): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT iv.id, iv.email, iv.role_granted, iv.personal_message,
               iv.expires_at, iv.accepted_at, iv.revoked_at, iv.created_at,
               ib.display_name AS invited_by_name,
               am.display_name AS accepted_by_name,
               CASE
                   WHEN iv.accepted_at IS NOT NULL THEN 'accepted'
                   WHEN iv.revoked_at  IS NOT NULL THEN 'revoked'
                   WHEN iv.expires_at  < now()     THEN 'expired'
                   ELSE 'pending'
               END AS status
        FROM invitations iv
        JOIN members ib ON ib.id = iv.invited_by
        LEFT JOIN members am ON am.id = iv.accepted_member_id
        ORDER BY (iv.accepted_at IS NULL AND iv.revoked_at IS NULL AND iv.expires_at > now()) DESC,
                 iv.created_at DESC
        LIMIT :lim
    SQL);
    $st->bindValue('lim', $limit, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}

function find_invitation(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT * FROM invitations WHERE id = :id');
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/**
 * Create an invitation. Returns ['ok'=>true,'invitation'=>row,'raw_token'=>...] or
 * ['ok'=>false,'error'=>msg]. Enforced-unique live invite per email (23505).
 */
function insert_invitation(PDO $pdo, string $email, string $role, int $invitedBy, ?string $message): array
{
    $raw = random_token();
    try {
        $st = $pdo->prepare(<<<'SQL'
            INSERT INTO invitations (email, role_granted, invited_by, personal_message, token_hash, expires_at)
            VALUES (:e, :r, :by, :msg, :h, now() + (:ttl || ' days')::interval)
            RETURNING *
        SQL);
        $st->execute([
            'e' => $email, 'r' => $role, 'by' => $invitedBy,
            'msg' => ($message === '' ? null : $message),
            'h' => hash_token($raw), 'ttl' => (string) INVITE_TTL_DAYS,
        ]);
        return ['ok' => true, 'invitation' => $st->fetch(), 'raw_token' => $raw];
    } catch (PDOException $ex) {
        if ($ex->getCode() === '23505') {
            return ['ok' => false, 'error' => 'A pending invitation already exists for that email.'];
        }
        throw $ex;
    }
}

/** Regenerate token + extend expiry for a still-pending invite. Returns raw token or null. */
function resend_invitation(PDO $pdo, int $id): ?string
{
    $raw = random_token();
    $st = $pdo->prepare(<<<'SQL'
        UPDATE invitations
        SET token_hash = :h, expires_at = now() + (:ttl || ' days')::interval
        WHERE id = :id AND accepted_at IS NULL AND revoked_at IS NULL
        RETURNING id
    SQL);
    $st->execute(['h' => hash_token($raw), 'ttl' => (string) INVITE_TTL_DAYS, 'id' => $id]);
    return $st->fetch() === false ? null : $raw;
}

function revoke_invitation(PDO $pdo, int $id): bool
{
    $st = $pdo->prepare(
        'UPDATE invitations SET revoked_at = now() WHERE id = :id AND accepted_at IS NULL AND revoked_at IS NULL'
    );
    $st->execute(['id' => $id]);
    return $st->rowCount() === 1;
}

// --------------------------------------------------------------------------
// Business OS invitations (2026-09-19) — /team/invitations. The cert-study functions above
// stay for what still calls them (registration's token lookup, the expiry cron).
// --------------------------------------------------------------------------

const INVITABLE_BUSINESS_ROLES = ['user', 'dept_admin', 'super_admin'];

/**
 * Pending invitations the caller may manage — read through mcp_business_invitations, which is
 * the rule: a super-admin sees all of them, a dept-admin those into departments they administer.
 */
function find_pending_business_invitations(PDO $pdo): array
{
    return $pdo->query(<<<'SQL'
        SELECT invitation_id, email, business_role_granted, invited_by, invited_by_name, expires_at, created_at,
               expires_at < now() AS expired
          FROM mcp_business_invitations
         ORDER BY created_at DESC
         LIMIT 200
    SQL)->fetchAll();
}

/** One pending invitation the caller may manage, or null (unknown, decided, or not theirs). */
function find_pending_business_invitation(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT * FROM mcp_business_invitations WHERE invitation_id = :id');
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/**
 * Invite someone into the business: what they will be (business role) and, optionally, the
 * department they join. `role_granted` is the legacy cert-study role and stays 'member'.
 */
function insert_business_invitation(PDO $pdo, string $email, string $businessRole, ?int $departmentId,
    int $invitedBy, ?string $message): array
{
    $raw = random_token();
    try {
        $st = $pdo->prepare(<<<'SQL'
            INSERT INTO invitations (email, role_granted, business_role_granted, department_id,
                                     invited_by, personal_message, token_hash, expires_at)
            VALUES (:e, 'member', :br, :dept, :by, :msg, :h, now() + (:ttl || ' days')::interval)
            RETURNING *
        SQL);
        $st->execute([
            'e' => $email, 'br' => $businessRole, 'dept' => $departmentId, 'by' => $invitedBy,
            'msg' => ($message === null || $message === '' ? null : $message),
            'h' => hash_token($raw), 'ttl' => (string) INVITE_TTL_DAYS,
        ]);
        return ['ok' => true, 'invitation' => $st->fetch(), 'raw_token' => $raw];
    } catch (PDOException $ex) {
        if ($ex->getCode() === '23505') {
            return ['ok' => false, 'error' => 'A pending invitation already exists for that email.'];
        }
        throw $ex;
    }
}

/**
 * What an accepted invitation grants, applied to the member it created — called inside the
 * registration transaction (password and Google alike). Until 2026-09-19 registration read only
 * the legacy role, so an invited department admin arrived as an ordinary user in no department.
 */
function apply_invitation_grants(PDO $pdo, array $invite, int $memberId): void
{
    $role = in_array($invite['business_role_granted'] ?? 'user', INVITABLE_BUSINESS_ROLES, true)
        ? (string) $invite['business_role_granted'] : 'user';
    $pdo->prepare('UPDATE members SET business_role = :r, is_external = :x WHERE id = :id')
        ->execute(['r' => $role, 'x' => !empty($invite['is_external_granted']) ? 'true' : 'false', 'id' => $memberId]);

    // A portal invitation (db/115): the company this External person is FOR is shared with them, which is what
    // every view keys an External caller's reach off. Nothing else is granted — no module, no department.
    if (!empty($invite['is_external_granted']) && ($invite['share_organization_id'] ?? null) !== null) {
        $pdo->prepare(<<<'SQL'
            INSERT INTO record_shares (entity_type, entity_id, member_id, access, shared_by)
            VALUES ('organization', :o, :m, 'read', :by)
            ON CONFLICT DO NOTHING
        SQL)->execute(['o' => (int) $invite['share_organization_id'], 'm' => $memberId, 'by' => $invite['invited_by'] ?? null]);
    }

    if (($invite['department_id'] ?? null) !== null) {
        $pdo->prepare(<<<'SQL'
            INSERT INTO department_members (department_id, member_id, is_admin, is_primary)
            VALUES (:d, :m, :admin, true)
            ON CONFLICT DO NOTHING
        SQL)->execute([
            'd' => (int) $invite['department_id'], 'm' => $memberId,
            'admin' => $role === 'dept_admin' ? 'true' : 'false',
        ]);
    }
}


/**
 * A portal invitation: an External person, for one company (docs/build-specs/portal-forms.md).
 * Accepting it shares that company with them — see apply_invitation_grants().
 */
function insert_portal_invitation(PDO $pdo, string $email, int $organizationId, int $invitedBy): array
{
    $raw = random_token();
    try {
        $st = $pdo->prepare(<<<'SQL'
            INSERT INTO invitations (email, role_granted, business_role_granted, is_external_granted, share_organization_id,
                                     invited_by, token_hash, expires_at)
            VALUES (:e, 'member', 'user', true, :org, :by, :h, now() + (:ttl || ' days')::interval)
            RETURNING *
        SQL);
        $st->execute(['e' => $email, 'org' => $organizationId, 'by' => $invitedBy, 'h' => hash_token($raw), 'ttl' => (string) INVITE_TTL_DAYS]);
        return ['ok' => true, 'invitation' => $st->fetch(), 'raw_token' => $raw];
    } catch (PDOException $ex) {
        if ($ex->getCode() === '23505') {
            return ['ok' => false, 'error' => 'A pending invitation already exists for that email.'];
        }
        throw $ex;
    }
}
