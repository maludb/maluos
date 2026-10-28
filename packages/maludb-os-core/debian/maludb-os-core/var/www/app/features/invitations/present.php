<?php
declare(strict_types=1);

/**
 * Invitation presenters. Whitelists, mirrored by web/lib/schemas/invitations.ts
 * (docs/react-migration-plan.md, "Presenters, never raw rows"). Never presented: the token hash,
 * the personal message, who the invitation is for beyond their address.
 */

const BUSINESS_ROLE_LABELS = ['user' => 'User', 'dept_admin' => 'Department admin', 'super_admin' => 'Super-admin'];

/** One pending invitation (find_pending_business_invitations()). */
function present_pending_invitation(array $i): array
{
    $role = (string) $i['business_role_granted'];
    return [
        'id' => (int) $i['invitation_id'],
        'email' => (string) $i['email'],
        'business_role' => $role,
        'business_role_label' => BUSINESS_ROLE_LABELS[$role] ?? $role,
        'invited_by_name' => (string) $i['invited_by_name'],
        'invited_by_member_id' => ($i['invited_by'] ?? null) !== null ? (int) $i['invited_by'] : null,
        'sent_at' => json_ts($i['created_at']),
        'expires_at' => json_ts($i['expires_at']),
        'expired' => (bool) $i['expired'],
    ];
}
