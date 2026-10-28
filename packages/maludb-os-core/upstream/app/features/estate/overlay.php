<?php
declare(strict_types=1);

/**
 * The overlay: the estate's own WireGuard network, the kernel half of Phase 13 slice 1b (maluos:
 * docs/phase13-slice1b-overlay.md; db/189). Every member (server, inference, desk) sends its WireGuard public
 * key at join or enroll and receives an address in the estate's range and a name (NAME.internal); the hub is the
 * coordinator's host, joined with --hub ENDPOINT; spokes keep one tunnel to the hub and reach each other through
 * it. The kernel allocates, keeps the public keys, and publishes the hub, the peers and the names; a version
 * bumped on every change tells heartbeating members to refresh at once (overlay_changed).
 */
require_once dirname(__DIR__, 2) . '/features/estate/desks.php';

const OVERLAY_REFRESH_S = 60;
const OVERLAY_QUARANTINE_DAYS = 30;
const OVERLAY_LISTEN_PORT = 51820;
const OVERLAY_NAME_SUFFIX = '.internal';

function overlay_settings(PDO $pdo): array
{
    $row = $pdo->query('SELECT * FROM estate_overlay WHERE id = 1')->fetch();
    return $row === false ? ['enabled' => false, 'range' => '100.100.0.0/16', 'hub_location_id' => null, 'hub_endpoint' => null, 'hub_public_key' => null, 'version' => 0] : $row;
}

function overlay_bump(PDO $pdo): void
{
    $pdo->exec('UPDATE estate_overlay SET version = version + 1, updated_at = now() WHERE id = 1');
}

/** A WireGuard public key: 32 bytes in base64, 44 characters ending in '='. */
function overlay_valid_key(?string $k): bool
{
    return is_string($k) && preg_match('/^[A-Za-z0-9+\/]{42}[AEIMQUYcgkosw048]=$/', $k) === 1;
}

/** host:port, the hub's endpoint as the spokes dial it. */
function overlay_valid_endpoint(?string $e): bool
{
    return is_string($e) && preg_match('/^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*|\d{1,3}(\.\d{1,3}){3}):\d{1,5}$/i', $e) === 1;
}

/** The DNS label a member goes by on the overlay: its name, lower case, [a-z0-9-], at most 63 characters. */
function overlay_label(string $name): string
{
    $s = strtolower(trim((string) iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $name)));
    $s = trim((string) preg_replace('/-+/', '-', (string) preg_replace('/[^a-z0-9]+/', '-', $s)), '-');
    return $s === '' ? 'node' : substr($s, 0, 63);
}

/** The IPv4 range as [network, broadcast] longs, or null for an IPv6 range (not served in this slice). */
function overlay_range(array $settings): ?array
{
    [$net, $bits] = array_pad(explode('/', (string) $settings['range'], 2), 2, '32');
    $n = ip2long($net);
    if ($n === false) { return null; }
    $size = 2 ** (32 - (int) $bits);
    return [$n, $n + $size - 1, (int) $bits];
}

/**
 * Give a member its key and address: the hub takes the first host address, a spoke the lowest address no live
 * member holds and no retired one freed within the quarantine. @return string the address
 */
function overlay_allocate(PDO $pdo, int $locationId, string $publicKey, bool $hub = false): string
{
    $s = overlay_settings($pdo);
    $r = overlay_range($s);
    if ($r === null) { throw new RuntimeException('the overlay range is not IPv4'); }
    [$lo, $hi, $bits] = $r;
    $cur = $pdo->prepare('SELECT overlay_address FROM locations WHERE id = :id');
    $cur->execute(['id' => $locationId]);
    $have = $cur->fetchColumn();
    if ($hub) {
        $addr = long2ip($lo + 1);
    } elseif (is_string($have) && $have !== '' && ip2long($have) > $lo + 1 && ip2long($have) < $hi) {
        $addr = $have;                                 // a re-join of the same row keeps its address
    } else {
        $st = $pdo->prepare('SELECT host(overlay_address) FROM locations WHERE overlay_address IS NOT NULL AND id <> :id
                               AND (overlay_address_freed_at IS NULL OR overlay_address_freed_at > now() - make_interval(days => :q))');
        $st->execute(['id' => $locationId, 'q' => OVERLAY_QUARANTINE_DAYS]);
        $used = array_fill_keys($st->fetchAll(PDO::FETCH_COLUMN), true);
        $addr = null;
        for ($a = $lo + 2; $a < $hi; $a++) {
            $ip = long2ip($a);
            if (!isset($used[$ip])) { $addr = $ip; break; }
        }
        if ($addr === null) { throw new RuntimeException('the overlay range is full'); }
    }
    $pdo->prepare('UPDATE locations SET overlay_public_key = :k, overlay_address = :a, overlay_address_freed_at = NULL, updated_at = now() WHERE id = :id')
        ->execute(['k' => $publicKey, 'a' => $addr, 'id' => $locationId]);
    if ($hub) {
        $pdo->prepare('UPDATE estate_overlay SET hub_location_id = :id, hub_public_key = :k, updated_at = now() WHERE id = 1')->execute(['id' => $locationId, 'k' => $publicKey]);
    }
    overlay_bump($pdo);
    return $addr;
}

/** The hub as the members see it, or null while none has joined (or it left). */
function overlay_hub(PDO $pdo): ?array
{
    $s = overlay_settings($pdo);
    if ($s['hub_location_id'] === null) { return null; }
    $st = $pdo->prepare("SELECT id, name, host(overlay_address) AS address, overlay_public_key FROM locations WHERE id = :id AND status = 'active' AND overlay_address IS NOT NULL");
    $st->execute(['id' => $s['hub_location_id']]);
    $h = $st->fetch();
    return $h === false ? null : ['id' => (int) $h['id'], 'name' => (string) $h['name'], 'public_key' => (string) ($s['hub_public_key'] ?: $h['overlay_public_key']),
                                  'endpoint' => (string) $s['hub_endpoint'], 'address' => (string) $h['address']];
}

/** Register $locationId as the hub with $endpoint; false when another active hub exists. */
function overlay_set_hub(PDO $pdo, int $locationId, string $endpoint): bool
{
    $h = overlay_hub($pdo);
    if ($h !== null && $h['id'] !== $locationId) { return false; }
    $pdo->prepare('UPDATE estate_overlay SET hub_location_id = :id, hub_endpoint = :e, updated_at = now() WHERE id = 1')->execute(['id' => $locationId, 'e' => $endpoint]);
    return true;
}

/** A member leaves the overlay (leave, retirement): its address is freed into quarantine; a hub leaving unsets the hub. */
function overlay_free(PDO $pdo, int $locationId): void
{
    $st = $pdo->prepare('UPDATE locations SET overlay_address_freed_at = now(), updated_at = now() WHERE id = :id AND overlay_address IS NOT NULL AND overlay_address_freed_at IS NULL RETURNING id');
    $st->execute(['id' => $locationId]);
    $freed = $st->fetch() !== false;
    $s = overlay_settings($pdo);
    if ((int) ($s['hub_location_id'] ?? 0) === $locationId) {
        $pdo->exec('UPDATE estate_overlay SET hub_location_id = NULL, hub_public_key = NULL, updated_at = now() WHERE id = 1');
        $freed = true;
    }
    if ($freed) { overlay_bump($pdo); }
}

/** A member's new key (rotation): the hub's is published to every spoke on their next refresh. */
function overlay_rotate(PDO $pdo, int $locationId, string $publicKey): void
{
    $pdo->prepare('UPDATE locations SET overlay_public_key = :k, updated_at = now() WHERE id = :id')->execute(['k' => $publicKey, 'id' => $locationId]);
    $s = overlay_settings($pdo);
    if ((int) ($s['hub_location_id'] ?? 0) === $locationId) {
        $pdo->prepare('UPDATE estate_overlay SET hub_public_key = :k, updated_at = now() WHERE id = 1')->execute(['k' => $publicKey]);
    }
    overlay_bump($pdo);
}

/** Every live member with an address: id, kind, name (the label), address, public key; labels made unique with -ID. */
function overlay_members(PDO $pdo): array
{
    $rows = $pdo->query("SELECT id, kind, name, host(overlay_address) AS address, overlay_public_key FROM locations
                          WHERE status = 'active' AND overlay_address IS NOT NULL AND overlay_address_freed_at IS NULL ORDER BY overlay_address")->fetchAll();
    $seen = [];
    $out = [];
    foreach ($rows as $r) {
        $label = overlay_label((string) $r['name']);
        if (isset($seen[$label])) { $label = substr($label, 0, 63 - strlen((string) $r['id']) - 1) . '-' . $r['id']; }
        $seen[$label] = true;
        $out[] = ['id' => (int) $r['id'], 'kind' => (string) $r['kind'], 'name' => $label, 'address' => (string) $r['address'], 'public_key' => (string) $r['overlay_public_key']];
    }
    return $out;
}

/** The member's label on the overlay (what overlay_members() gives it). */
function overlay_member_name(PDO $pdo, int $locationId): ?string
{
    foreach (overlay_members($pdo) as $m) { if ($m['id'] === $locationId) { return $m['name']; } }
    return null;
}

/**
 * The `overlay` block of a join, enroll, me or heartbeat answer: null when the estate's overlay is off, the member
 * has no address (opted out, or an older client), or no hub has joined yet (the member's address is kept meanwhile).
 */
function overlay_block(PDO $pdo, array $loc): ?array
{
    $s = overlay_settings($pdo);
    if (empty($s['enabled']) || ($loc['overlay_address'] ?? null) === null || ($loc['overlay_address_freed_at'] ?? null) !== null) { return null; }
    $hub = overlay_hub($pdo);
    $isHub = $hub !== null && $hub['id'] === (int) $loc['id'];
    if ($hub === null && !$isHub) { return null; }
    $r = overlay_range($s);
    return ['address' => (string) $loc['overlay_address'], 'prefix' => $r !== null ? $r[2] : 16, 'name' => overlay_member_name($pdo, (int) $loc['id']) . OVERLAY_NAME_SUFFIX,
            'hub' => $isHub ? null : ['public_key' => $hub['public_key'], 'endpoint' => $hub['endpoint'], 'address' => $hub['address']],
            'role' => $isHub ? 'hub' : 'spoke', 'listen_port' => $isHub ? OVERLAY_LISTEN_PORT : null];
}

/** GET /api/v1/estate/overlay and /api/v1/desks/overlay: self, the hub, the peers to configure, every name. */
function overlay_answer(PDO $pdo, array $loc): array
{
    $hub = overlay_hub($pdo);
    $isHub = $hub !== null && $hub['id'] === (int) $loc['id'];
    $members = overlay_members($pdo);
    $me = null;
    foreach ($members as $m) { if ($m['id'] === (int) $loc['id']) { $me = $m; } }
    $peers = [];
    if ($isHub) {
        foreach ($members as $m) { if ($m['id'] !== (int) $loc['id'] && $m['public_key'] !== '') { $peers[] = ['public_key' => $m['public_key'], 'address' => $m['address'], 'name' => $m['name']]; } }
    } elseif ($hub !== null) {
        $peers[] = ['public_key' => $hub['public_key'], 'address' => $hub['address'], 'name' => overlay_member_name($pdo, $hub['id']) ?? overlay_label($hub['name'])];
    }
    return ['ok' => true, 'surface' => DESK_SURFACE, 'fetched_at' => gmdate('Y-m-d\TH:i:s\Z'),
            'self' => $me !== null ? ['address' => $me['address'], 'name' => $me['name'] . OVERLAY_NAME_SUFFIX, 'role' => $isHub ? 'hub' : 'spoke'] : null,
            'hub' => $hub !== null ? ['public_key' => $hub['public_key'], 'endpoint' => $hub['endpoint'], 'address' => $hub['address'], 'name' => overlay_label($hub['name']) . OVERLAY_NAME_SUFFIX] : null,
            'peers' => $peers,
            'names' => array_map(static fn ($m) => ['name' => $m['name'], 'address' => $m['address'], 'kind' => $m['kind']], $members),
            'refresh_s' => OVERLAY_REFRESH_S, 'version' => (int) overlay_settings($pdo)['version']];
}

/** Whether the overlay changed since this member last heard (a heartbeat answer's overlay_changed); marks it heard. */
function overlay_changed(PDO $pdo, array $loc): bool
{
    $v = (int) overlay_settings($pdo)['version'];
    $seen = (int) ($loc['overlay_seen_version'] ?? 0);
    if ($seen === $v) { return false; }
    $pdo->prepare('UPDATE locations SET overlay_seen_version = :v WHERE id = :id')->execute(['v' => $v, 'id' => $loc['id']]);
    return true;
}

/** A member has heard the overlay as it is now (the join and enroll answers carry it all). */
function overlay_mark_seen(PDO $pdo, int $locationId): void
{
    $pdo->prepare('UPDATE locations SET overlay_seen_version = (SELECT version FROM estate_overlay WHERE id = 1) WHERE id = :id')->execute(['id' => $locationId]);
}

/** The join's and enroll's overlay part: the key from the body, the address, the hub registration. @return ?string an error code */
function overlay_join(PDO $pdo, int $locationId, array $body): ?string
{
    $s = overlay_settings($pdo);
    $key = $body['overlay_public_key'] ?? null;
    if (empty($s['enabled']) || !overlay_valid_key(is_string($key) ? $key : null)) { overlay_mark_seen($pdo, $locationId); return null; }
    $hubReq = is_array($body['overlay_hub'] ?? null) ? $body['overlay_hub'] : null;
    if ($hubReq !== null) {
        $endpoint = $hubReq['endpoint'] ?? null;
        if (!overlay_valid_endpoint(is_string($endpoint) ? $endpoint : null)) { return 'invalid_endpoint'; }
        if (!overlay_set_hub($pdo, $locationId, $endpoint)) { return 'hub_exists'; }
        overlay_allocate($pdo, $locationId, $key, true);
    } else {
        overlay_allocate($pdo, $locationId, $key, false);
    }
    overlay_mark_seen($pdo, $locationId);
    return null;
}

/** Settings → Desks for an operator: the overlay's state. */
function present_overlay_for_settings(PDO $pdo): array
{
    $s = overlay_settings($pdo);
    $hub = overlay_hub($pdo);
    return ['enabled' => !empty($s['enabled']), 'range' => (string) $s['range'],
            'hub' => $hub !== null ? ['id' => $hub['id'], 'name' => $hub['name'], 'endpoint' => $hub['endpoint'], 'address' => $hub['address']] : null,
            'members' => count(overlay_members($pdo))];
}
