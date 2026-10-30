<?php
declare(strict_types=1);

/**
 * Desks: a MaluOS desktop enrolled with this office — the kernel half of desk enrolment
 * (docs/build-specs/desk-enrolment.md, stage D2; db/187). The contract is the desk's, surface 1
 * (maluos: docs/desk-enrolment.md): a one-time code a person mints for themselves is exchanged
 * for a DESK TOKEN (mcp_access_tokens, scope 'desk', bound to the desk's location row); the desk
 * heartbeats its presence with it, reads records and activity as its owner, and leaves with it.
 * A desk never widens its owner's reach: the token resolves to the owner and nothing else.
 */
require_once dirname(__DIR__, 2) . '/features/estate/queries.php';

require_once __DIR__ . '/inference.php';      // db/191: the inference key at enrol, the editions in the answer, retirement

const DESK_SURFACE = 1;
const DESK_HEARTBEAT_S = 300;
const DESK_CODE_TTL_S = 900;
const DESK_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';   // no 0/O, 1/I: it is read aloud and typed

// --------------------------------------------------------------------------
// Codes
// --------------------------------------------------------------------------
function desk_code_normalize(string $raw): string
{
    return strtoupper((string) preg_replace('/[^A-Za-z0-9]/', '', $raw));
}

/**
 * Mint a code for $memberId: eight characters, fifteen minutes, one use. A person has one live code
 * at a time — minting again expires the earlier one. @return array{code:string,expires_at:string,id:int}
 */
function desk_code_mint(PDO $pdo, int $memberId, ?string $deskName, int $createdBy, string $kind = 'desk'): array
{
    // db/188: a code is minted for a kind; a node code (server, inference) is the operator's, and they may hold one per kind.
    $pdo->prepare('UPDATE desk_enrollment_codes SET expires_at = now() WHERE member_id = :m AND kind = :k AND used_at IS NULL AND expires_at > now()')
        ->execute(['m' => $memberId, 'k' => $kind]);
    $code = '';
    for ($i = 0; $i < 8; $i++) {
        $code .= DESK_CODE_ALPHABET[random_int(0, strlen(DESK_CODE_ALPHABET) - 1)];
    }
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO desk_enrollment_codes (member_id, code_hash, desk_name, expires_at, created_by, kind)
        VALUES (:m, :h, :n, now() + make_interval(secs => :ttl), :b, :k)
        RETURNING id, expires_at
    SQL);
    $st->execute(['m' => $memberId, 'h' => hash('sha256', $code), 'n' => $deskName !== '' ? $deskName : null, 'ttl' => DESK_CODE_TTL_S, 'b' => $createdBy, 'k' => $kind]);
    $row = $st->fetch();
    return ['code' => substr($code, 0, 4) . '-' . substr($code, 4), 'expires_at' => (string) $row['expires_at'], 'id' => (int) $row['id']];
}

/** The live, unused, unexpired code row for $raw of one of $kinds (db/188: a desk code enrols only a desk), locked for this transaction, or null. */
function desk_code_take(PDO $pdo, string $raw, array $kinds = ['desk']): ?array
{
    $norm = desk_code_normalize($raw);
    if (strlen($norm) !== 8) {
        return null;
    }
    $st = $pdo->prepare('SELECT * FROM desk_enrollment_codes WHERE code_hash = :h AND kind = ANY(:kinds) AND used_at IS NULL AND expires_at > now() FOR UPDATE');
    $st->execute(['h' => hash('sha256', $norm), 'kinds' => '{' . implode(',', $kinds) . '}']);
    $row = $st->fetch();
    return $row === false ? null : $row;
}

// --------------------------------------------------------------------------
// Enrolment
// --------------------------------------------------------------------------
/** The office the owner works at: the home location of their primary department, else of any of their departments. */
function desk_office_location_id(PDO $pdo, int $memberId): ?int
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT d.home_location_id
          FROM department_members dm
          JOIN departments d ON d.id = dm.department_id AND d.archived_at IS NULL
          JOIN locations l ON l.id = d.home_location_id AND l.status = 'active' AND l.kind = 'office'
         WHERE dm.member_id = :m AND dm.left_at IS NULL
         ORDER BY dm.is_primary DESC, dm.joined_at
         LIMIT 1
    SQL);
    $st->execute(['m' => $memberId]);
    $id = $st->fetchColumn();
    return $id === false || $id === null ? null : (int) $id;
}

/** The facts a desk reports about itself, as location columns; only what was given. */
function desk_facts(array $body): array
{
    $int = static fn ($v): ?int => is_numeric($v) && (int) $v > 0 ? (int) $v : null;
    $str = static fn ($v, int $max): ?string => is_string($v) && trim($v) !== '' ? mb_substr(trim($v), 0, $max) : null;
    return array_filter([
        'hostname' => $str($body['hostname'] ?? null, 120),
        'os_platform' => $str($body['os_platform'] ?? null, 40),
        'operating_system' => $str($body['os_release'] ?? null, 120),
        'app_version' => $str($body['app_version'] ?? null, 80),
        'mcp_surface_version' => $str($body['mcp_surface_version'] ?? null, 20),
        'cpu_cores' => $int($body['cpu_cores'] ?? null),
        'memory_mb' => $int($body['memory_mb'] ?? null),
        'storage_gb' => $int($body['storage_gb'] ?? null),
        'machine_id' => is_string($body['machine_id'] ?? null) && preg_match('/^[0-9a-f]{16,64}$/', $body['machine_id']) ? $body['machine_id'] : null,
    ], static fn ($v) => $v !== null);
}

/**
 * Make the desk for the code's member and mint its token, in one transaction: a previous desk of theirs
 * with the same machine_id is retired first (its token revoked). @return array{desk:array,token:string}
 * Throws PDOException 23505 when the name is taken (locations.name is unique).
 */
function desk_enroll(PDO $pdo, array $code, array $body, ?string $principal): array
{
    $member = find_member_by_id($pdo, (int) $code['member_id']);
    if ($member === null) {
        throw new RuntimeException('no member');
    }
    $facts = desk_facts($body);
    $name = is_string($body['name'] ?? null) && trim($body['name']) !== '' ? mb_substr(trim($body['name']), 0, 120)
        : ((string) ($code['desk_name'] ?? '') !== '' ? (string) $code['desk_name'] : $member['display_name'] . "'s desk");
    if (isset($facts['machine_id'])) {
        $old = $pdo->prepare("SELECT id FROM locations WHERE kind = 'desk' AND status = 'active' AND owner_member_id = :m AND machine_id = :mid");
        $old->execute(['m' => $member['id'], 'mid' => $facts['machine_id']]);
        foreach ($old->fetchAll(PDO::FETCH_COLUMN) as $oldId) {
            desk_retire($pdo, (int) $oldId);
            log_activity($pdo, 'desk.retire', 'location', (int) $oldId, ['source' => 'desk', 'after' => ['reason' => 'the same machine enrolled again']]);
        }
    }
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO locations
            (name, kind, parent_location_id, owner_member_id, is_always_on, external_ref, presence, last_seen_at, enrolled_at,
             hostname, os_platform, operating_system, app_version, mcp_surface_version, cpu_cores, memory_mb, storage_gb, machine_id,
             platform, siting)
        VALUES
            (:name, 'desk', :parent, :owner, false, :ref, 'online', now(), now(),
             :hostname, :os_platform, :operating_system, :app_version, :mcp_surface_version, :cpu_cores, :memory_mb, :storage_gb, :machine_id,
             'desktop', 'offsite')
        RETURNING id
    SQL);
    $st->execute([
        'name' => $name, 'parent' => desk_office_location_id($pdo, (int) $member['id']), 'owner' => $member['id'],
        'ref' => $principal !== null ? mb_substr($principal, 0, 120) : null,
        'hostname' => $facts['hostname'] ?? null, 'os_platform' => $facts['os_platform'] ?? null,
        'operating_system' => $facts['operating_system'] ?? null, 'app_version' => $facts['app_version'] ?? null,
        'mcp_surface_version' => $facts['mcp_surface_version'] ?? null, 'cpu_cores' => $facts['cpu_cores'] ?? null,
        'memory_mb' => $facts['memory_mb'] ?? null, 'storage_gb' => $facts['storage_gb'] ?? null, 'machine_id' => $facts['machine_id'] ?? null,
    ]);
    $deskId = (int) $st->fetchColumn();

    $raw = 'desk_' . bin2hex(random_bytes(24));
    $st = $pdo->prepare("INSERT INTO mcp_access_tokens (member_id, label, token_hash, scope, location_id) VALUES (:m, :l, :h, 'desk', :loc) RETURNING id");
    $st->execute(['m' => $member['id'], 'l' => 'Desk: ' . $name, 'h' => hash('sha256', $raw), 'loc' => $deskId]);
    $tokenId = (int) $st->fetchColumn();
    $pdo->prepare('UPDATE locations SET enrollment_token_id = :t WHERE id = :id')->execute(['t' => $tokenId, 'id' => $deskId]);
    $pdo->prepare('UPDATE desk_enrollment_codes SET used_at = now(), location_id = :loc WHERE id = :id')->execute(['loc' => $deskId, 'id' => $code['id']]);
    return ['desk' => desk_row($pdo, $deskId), 'token' => $raw];
}

/** The desk's own row (locations, not the view: the endpoints run as the owner, who may not be an insider of anything else). */
function desk_row(PDO $pdo, int $id): array
{
    $st = $pdo->prepare("SELECT * FROM locations WHERE id = :id AND kind = 'desk'");
    $st->execute(['id' => $id]);
    $row = $st->fetch();
    return $row === false ? [] : $row;
}

/**
 * Revoke a desk's token. Called wherever a desk stops being one — leave, a retirement from Work Locations,
 * a re-enrolment of the same machine, a deletion — because the MCP servers resolve any live token to its
 * member regardless of scope (db/014): a retired desk's token must not read as the owner anywhere.
 */
function desk_revoke_tokens(PDO $pdo, int $id): void
{
    $pdo->prepare("UPDATE mcp_access_tokens SET revoked_at = now() WHERE scope = 'desk' AND location_id = :id AND revoked_at IS NULL")
        ->execute(['id' => $id]);
}

/** Retire a desk and revoke its token (leave, a re-enrolment). Work Locations' retire.php does the same for a desk. */
function desk_retire(PDO $pdo, int $id): void
{
    $pdo->prepare("UPDATE locations SET status = 'retired', retired_at = COALESCE(retired_at, now()), presence = 'offline', updated_at = now() WHERE id = :id")
        ->execute(['id' => $id]);
    desk_revoke_tokens($pdo, $id);
    overlay_free($pdo, $id);      // db/189: its overlay address into quarantine
    inference_member_retire($pdo, $id);      // db/191
}

function desk_heartbeat(PDO $pdo, int $id, string $presence, array $body): void
{
    $facts = desk_facts(is_array($body['facts'] ?? null) ? $body['facts'] + $body : $body);
    unset($facts['machine_id']);
    $sets = ['presence = :presence', 'last_seen_at = now()', 'updated_at = now()'];
    $params = ['presence' => $presence, 'id' => $id];
    foreach ($facts as $col => $v) {
        $sets[] = "{$col} = :{$col}";
        $params[$col] = $v;
    }
    $pdo->prepare('UPDATE locations SET ' . implode(', ', $sets) . ' WHERE id = :id')->execute($params);
}

/** The presence job: a desk that stopped heartbeating (power, network) is offline after three missed beats. */
function desk_presence_sweep(PDO $pdo): array
{
    $st = $pdo->prepare(<<<'SQL'
        UPDATE locations SET presence = 'offline', updated_at = now()
         WHERE kind = 'desk' AND status = 'active' AND presence = 'online'
           AND last_seen_at < now() - make_interval(secs => :s)
        RETURNING id, name
    SQL);
    $st->execute(['s' => 3 * DESK_HEARTBEAT_S]);
    return $st->fetchAll();
}

// --------------------------------------------------------------------------
// The endpoints' authentication and answer
// --------------------------------------------------------------------------
/**
 * Resolve the bearer desk token: 401 for anything but a live desk token (one message, never which
 * reason), 410 once the desk is retired. Sets the request context to the owner, as api_authenticate()
 * does, so every later query and activity row is theirs. @return array{token:array,desk:array,member:array}
 */
function desk_authenticate(): array
{
    $pdo = db();
    $raw = api_bearer_token();
    if ($raw === '') {
        api_error('unauthorized', 'A valid desk token is required.', 401);
    }
    $st = $pdo->prepare("SELECT * FROM mcp_access_tokens WHERE token_hash = :h AND scope = 'desk' AND (expires_at IS NULL OR expires_at > now())");
    $st->execute(['h' => hash('sha256', $raw)]);
    $token = $st->fetch();
    if ($token === false || $token['location_id'] === null) {
        error_log('desk auth: token rejected (missing, wrong scope or expired)');
        api_error('unauthorized', 'A valid desk token is required.', 401);
    }
    $desk = desk_row($pdo, (int) $token['location_id']);
    // A desk that was retired (by the office, by leaving, by the same machine enrolling again) had its token
    // revoked at that moment; the token still tells the desk WHY it is refused, so its session can say so.
    if ($desk !== [] && $desk['status'] !== 'active') {
        api_error('retired', 'This desk was retired by the office.', 410);
    }
    $member = find_member_by_id($pdo, (int) $token['member_id']);
    if ($token['revoked_at'] !== null || $desk === [] || $member === null || $member['status'] !== 'active') {
        error_log('desk auth: token revoked, or it maps to no desk or an inactive owner');
        api_error('unauthorized', 'A valid desk token is required.', 401);
    }
    $pdo->prepare('UPDATE mcp_access_tokens SET last_used_at = now() WHERE id = :id')->execute(['id' => $token['id']]);
    $_SESSION['member_id'] = (int) $member['id'];
    $_SESSION['member_role'] = $member['role'];
    $GLOBALS['__api_token_authed'] = true;
    db_apply_context($pdo);
    return ['token' => $token, 'desk' => $desk, 'member' => $member];
}

/** The JSON body of a desk call (application/json), or []. */
function desk_body(): array
{
    $body = json_decode((string) file_get_contents('php://input'), true);
    return is_array($body) ? $body : [];
}

/** Who reads the estate and mints node codes (db/188): the business's super-admins, the system managers of Phase 13 slice 1. */
function estate_operator(?array $member): bool
{
    return $member !== null && ($member['business_role'] ?? '') === 'super_admin' && ($member['status'] ?? '') === 'active';
}

/** What this office publishes to desks. memory, actions and models stay null until their own slice; estate (db/188) to an operator's desk. */
function desk_endpoints(?array $member = null): array
{
    return [
        'heartbeat' => app_url('/api/v1/desks/heartbeat'), 'me' => app_url('/api/v1/desks/me'), 'leave' => app_url('/api/v1/desks/leave'),
        'records' => app_url('/mcp/records'), 'activity' => app_url('/mcp/activity'),
        'memory' => null, 'actions' => null, 'models' => null,
        'estate' => estate_operator($member) ? app_url('/api/v1/desks/estate') : null,
        // db/190: the directory as this desk sees it, the person's estate inbox, the desk's key registration, the keys
        'agents' => app_url('/api/v1/desks/agents'), 'inbox' => app_url('/api/v1/desks/inbox'), 'key' => app_url('/api/v1/desks/key'), 'keys' => app_url('/api/v1/estate/keys'),
        'actions' => estate_operator($member) ? app_url('/api/v1/estate/actions') : null,
        // db/191: the backends this desk may use; a desk that shares its GPU reads its peers at the estate endpoint
        'inference' => app_url('/api/v1/desks/inference'), 'inference_peers' => app_url('/api/v1/estate/inference/peers'),
    ];
}

/** The contract's answer for heartbeat, me and (with the token added by the caller) enroll. */
function desk_answer(PDO $pdo, array $desk, array $member): array
{
    $overlay = overlay_block($pdo, $desk);      // db/189: the desk's place on the estate's network, or null
    $endpoints = desk_endpoints($member);
    $endpoints['overlay'] = $overlay !== null ? app_url('/api/v1/desks/overlay') : null;
    return [
        'ok' => true, 'surface' => DESK_SURFACE,
        'desk' => ['id' => (int) $desk['id'], 'name' => (string) $desk['name'], 'status' => (string) $desk['status'],
                   'presence' => (string) $desk['presence'], 'last_seen_at' => json_ts($desk['last_seen_at'] ?? null)],
        'office' => ['name' => business_name($pdo), 'url' => app_url('/')],
        'owner' => ['member_id' => (int) $member['id'], 'email' => (string) $member['email'], 'display_name' => (string) $member['display_name']],
        'endpoints' => $endpoints, 'heartbeat_s' => DESK_HEARTBEAT_S, 'overlay' => $overlay,
        'editions' => inference_editions($pdo),      // db/191
    ];
}

// --------------------------------------------------------------------------
// The person's own desks (Settings)
// --------------------------------------------------------------------------
function find_my_desks(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT id, name, status, presence, last_seen_at, enrolled_at, hostname, os_platform, operating_system, app_version
          FROM locations
         WHERE kind = 'desk' AND owner_member_id = :m AND status = 'active'
         ORDER BY enrolled_at DESC NULLS LAST, name
    SQL);
    $st->execute(['m' => $memberId]);
    return $st->fetchAll();
}

function present_desk(array $l): array
{
    return [
        'id' => (int) $l['id'], 'name' => (string) $l['name'], 'presence' => (string) $l['presence'],
        'last_seen_at' => json_ts($l['last_seen_at'] ?? null), 'enrolled_at' => json_ts($l['enrolled_at'] ?? null),
        'hostname' => $l['hostname'] !== null ? (string) $l['hostname'] : null,
        'os' => trim((string) ($l['operating_system'] ?? '')) !== '' ? (string) $l['operating_system'] : ($l['os_platform'] !== null ? (string) $l['os_platform'] : null),
        'app_version' => $l['app_version'] !== null ? (string) $l['app_version'] : null,
    ];
}

// db/189: the overlay's functions (desk_answer and desk_retire call them); loaded last so the circular require is harmless.
require_once __DIR__ . '/overlay.php';
// db/190: the agent directory and delegation (heartbeats register agents, leave deregisters them, desks read their inbox).
require_once __DIR__ . '/delegation.php';
