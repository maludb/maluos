<?php
declare(strict_types=1);

/**
 * Sign-on into an application from us (A3, 2026-09-22 — docs/business-os-integration.md,
 * "Identity and single sign-on"; docs/build-specs/kernel-sign-on.md).
 *
 * The kernel is the one identity. The launcher mints a hand-off token for a person with a live
 * access grant and sends the browser to the application's sso path; the application verifies it
 * with the tenant's ACTION_TOKEN_KEY, opens its own session, and refreshes its directory mirror
 * from the signed claims beside the token. Sign-out here posts a notice to every application the
 * person entered this session. Nothing here is ever an agent's: an agent's credential is its run
 * token, on MCP.
 */

const SSO_TOKEN_TTL = 60;          // seconds; single use — the application records the nonce
const SSO_LOGOUT_TTL = 120;

/**
 * What the member holds on one application (db/141, db/145): on a scoped application every scope with
 * its roles; on one that declares roles, the roles. `role` is the highest of them (what one-role readers
 * had); `roles` every role held, `rights` the union of the rights those roles publish (app_roles). Shared
 * by the claims, the change feed and run facts, so the three never disagree.
 *   ['role' => ?string, 'roles' => string[], 'rights' => string[], 'capability' => ?string,
 *    'scopes' => [{scope_id, kind, id, name, role, roles, rights, capability}]]
 */
function sso_member_holding(PDO $pdo, int $applicationId, int $memberId): array
{
    $st = $pdo->prepare('SELECT scope_kind FROM applications WHERE id = :id');
    $st->execute(['id' => $applicationId]);
    $scopeKind = (string) ($st->fetchColumn() ?: 'none');
    // Every role reaching the member, per scope, and what each role's rights are.
    $st = $pdo->prepare('SELECT k.scope_id, k.role_key, r.rights FROM app_member_role_keys(:a, :m) k
                           JOIN application_roles r ON r.application_id = :a AND r.role_key = k.role_key');
    $st->execute(['a' => $applicationId, 'm' => $memberId]);
    $byScope = [];
    foreach ($st->fetchAll() as $r) {
        $at = $r['scope_id'] === null ? 0 : (int) $r['scope_id'];
        $byScope[$at]['roles'][] = (string) $r['role_key'];
        foreach (json_decode((string) $r['rights'], true) ?: [] as $right) {
            $key = is_array($right) ? (string) ($right['key'] ?? '') : (string) $right;
            if ($key !== '') {
                $byScope[$at]['rights'][$key] = true;
            }
        }
    }
    $rolesAt = static fn (int $at): array => array_values(array_unique($byScope[$at]['roles'] ?? []));
    $rightsAt = static fn (int $at): array => array_keys($byScope[$at]['rights'] ?? []);

    if ($scopeKind === 'none') {
        $st = $pdo->prepare('SELECT role_key, capability FROM app_member_application_role(:a, :m)');
        $st->execute(['a' => $applicationId, 'm' => $memberId]);
        $row = $st->fetch() ?: [];
        return ['role' => $row['role_key'] ?? null, 'roles' => $rolesAt(0), 'rights' => $rightsAt(0),
                'capability' => $row['capability'] ?? null, 'scopes' => []];
    }
    $st = $pdo->prepare('SELECT * FROM app_member_application_scopes(:a, :m)');
    $st->execute(['a' => $applicationId, 'm' => $memberId]);
    $scopes = [];
    $best = null;
    $allRoles = [];
    $allRights = [];
    foreach ($st->fetchAll() as $r) {
        $at = (int) $r['scope_id'];
        $scopes[] = [
            'scope_id' => $at,
            'kind' => (string) $r['scope_kind'],
            'id' => (int) ($r['location_id'] ?? $r['department_id']),
            'name' => (string) $r['scope_name'],
            'role' => $r['role_key'] !== null ? (string) $r['role_key'] : null,
            'roles' => $rolesAt($at),
            'rights' => $rightsAt($at),
            'capability' => (string) $r['capability'],
        ];
        $allRoles = array_merge($allRoles, $rolesAt($at));
        $allRights = array_merge($allRights, $rightsAt($at));
        if ($best === null || app_capability_rank_php((string) $r['capability']) > app_capability_rank_php($best)) {
            $best = (string) $r['capability'];
        }
    }
    return ['role' => null, 'roles' => array_values(array_unique($allRoles)), 'rights' => array_values(array_unique($allRights)),
            'capability' => $best, 'scopes' => $scopes];
}

/**
 * K38 (2026-10-10; docs/build-specs/kernel-run-facts-requester.md): WHO AN AGENT'S RUN ACTS FOR. For a run a person (or an orchestrator acting
 * for one) started — trigger chat, manual or delegation — the member recorded in agent_runs.requested_by, and whether that member holds THIS
 * application; null for a duty, an evaluation or a message (they act as the agent alone) and when the requester is the agent itself. The
 * application intersects the agent's access with the requester's (the Data Lake's rule 8), so a chat turn never reads more than the person may.
 *
 * @return array{requested_by_member_id: ?int, requested_by_kind: ?string, requested_by_holds: bool}
 */
function run_facts_requester(PDO $pdo, int $applicationId, int $runId, int $agentMemberId): array
{
    $none = ['requested_by_member_id' => null, 'requested_by_kind' => null, 'requested_by_holds' => false];
    $st = $pdo->prepare("SELECT r.requested_by, r.trigger, m.member_kind, m.status FROM agent_runs r JOIN members m ON m.id = r.requested_by
                          WHERE r.id = :r AND r.agent_member_id = :a");
    $st->execute(['r' => $runId, 'a' => $agentMemberId]);
    $row = $st->fetch() ?: null;
    if ($row === null || !in_array((string) $row['trigger'], ['chat', 'manual', 'delegation'], true)
        || (int) $row['requested_by'] === $agentMemberId) {
        return $none;
    }
    $holding = sso_member_holding($pdo, $applicationId, (int) $row['requested_by']);
    return [
        'requested_by_member_id' => (int) $row['requested_by'],
        'requested_by_kind' => (string) $row['member_kind'],
        'requested_by_holds' => $row['status'] === 'active' && $holding['capability'] !== null,
    ];
}

function app_capability_rank_php(string $capability): int
{
    return ['read' => 1, 'write' => 2, 'admin' => 3][$capability] ?? 0;
}

/** The signed claims an application refreshes its directory mirror from: exactly these, nothing more. */
function sso_claims(PDO $pdo, array $member, string $capability, array $holding = ['role' => null, 'scopes' => []], ?int $scope = null): array
{
    require_once dirname(__DIR__) . '/team/queries.php';
    $departments = array_map(static fn (array $d): array => [
        'id' => (int) $d['department_id'], 'name' => (string) $d['department_name'], 'is_admin' => !empty($d['is_admin']),
    ], member_departments($pdo, (int) $member['id']));
    return [
        'member_id' => (int) $member['id'],
        'display_name' => (string) ($member['display_name'] ?? ''),
        'email' => (string) ($member['email'] ?? ''),
        'business_role' => (string) ($member['business_role'] ?? 'user'),
        'is_external' => !empty($member['is_external']),
        'status' => (string) ($member['status'] ?? 'active'),
        'departments' => $departments,
        'capability' => $capability,
        // db/141, additive: the application's own role (unscoped with roles), every scope held (scoped),
        // and the scope the person chose on the launcher.
        'role' => $holding['role'] ?? null,
        // db/145, additive: every role held and the rights they give (on a scoped application, the
        // union over its scopes; each scope in `scopes` carries its own).
        'roles' => $holding['roles'] ?? [],
        'rights' => $holding['rights'] ?? [],
        'scopes' => $holding['scopes'] ?? [],
        'scope' => $scope,
    ];
}

/**
 * The address the browser is sent to: the application's url + sso path, carrying the token and the
 * claims. The application's url is the name people reach it by (its own virtual host), never an
 * internal port.
 */
function sso_launch_url(PDO $pdo, array $application, array $member, string $capability, array $holding = ['role' => null, 'scopes' => []], ?int $scope = null): string
{
    $token = mint_sso_token((int) $member['id'], (string) $application['app_key'], SSO_TOKEN_TTL);
    $claims = sign_sso_claims(sso_claims($pdo, $member, $capability, $holding, $scope));
    $base = rtrim((string) $application['url'], '/') . (string) $application['sso_path'];
    return $base . (str_contains($base, '?') ? '&' : '?') . http_build_query(['token' => $token, 'claims' => $claims]);
}

/**
 * Tell each application the person signed in to this session that they have signed out. Best
 * effort and quick: a notice that does not arrive costs nothing — the application's own sign-out
 * ends its session, and its directory mirror catches a deactivation from the change feed (A4).
 * Returns what was notified, for the activity log.
 */
function sso_logout_notices(PDO $pdo, int $memberId, array $sessionApps): array
{
    $result = [];
    if ($sessionApps === [] || !function_exists('curl_init')) {
        return $result;
    }
    $ids = array_map('intval', array_keys($sessionApps));
    $in = implode(',', array_fill(0, count($ids), '?'));
    $st = $pdo->prepare("SELECT id, app_key, url, sso_logout_path FROM applications
                          WHERE id IN ({$in}) AND status <> 'retired' AND url IS NOT NULL AND sso_logout_path IS NOT NULL");
    $st->execute($ids);
    foreach ($st->fetchAll() as $app) {
        $notice = mint_sso_logout_notice($memberId, (string) $app['app_key'], SSO_LOGOUT_TTL);
        $ch = curl_init(rtrim((string) $app['url'], '/') . (string) $app['sso_logout_path']);
        curl_setopt_array($ch, [
            CURLOPT_POST => true, CURLOPT_POSTFIELDS => http_build_query(['notice' => $notice]),
            CURLOPT_RETURNTRANSFER => true, CURLOPT_CONNECTTIMEOUT => 2, CURLOPT_TIMEOUT => 3,
            CURLOPT_HTTPHEADER => ['Accept: application/json'],
        ]);
        curl_exec($ch);
        $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);
        $result[(string) $app['app_key']] = $status;
    }
    return $result;
}
