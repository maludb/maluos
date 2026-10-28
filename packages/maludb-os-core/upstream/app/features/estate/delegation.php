<?php
declare(strict_types=1);

/**
 * The agent directory and delegation, the kernel half of Phase 13 slice 2 (db/190; maluos
 * docs/phase13-slice2-delegation.md).
 *
 * - The ENVELOPE: a signed JSON object a sender puts on tasks/send (and on a node action, a reply or a decision).
 *   Canonical form for signing: the object without `sig`, every member whose value is null, [] or {} omitted,
 *   keys sorted at every level, no whitespace, slashes and unicode unescaped (the hosts' Python does the same;
 *   bin/test_estate_delegation.php proves the two agree). Signed with ed25519 by a node's key (desk:ID,
 *   server:ID, inference:ID) or the coordinator's own; the public keys come from GET /api/v1/estate/keys.
 * - The DIRECTORY (estate_agents): what each node registers from its manifests.
 * - TASKS (estate_tasks): stored by the kernel, leased to the agent's node when it long-polls its inbox,
 *   done with the result and its provenance. A task that waits for a person (an approval, a question) parks
 *   as pending_approval and the person's estate inbox carries the question; their answer re-queues it.
 * - ACTIONS (estate_actions): a system manager's restart_agent, start_agent, stop_agent, apply_updates, reboot.
 * - The person's INBOX (estate_inbox), long-polled by their desk.
 *
 * Requires app/features/estate/nodes.php (which requires desks.php and overlay.php).
 */

const ENVELOPE_VERSION = 1;
const ENVELOPE_MAX_LIFE_S = 3600;
const ENVELOPE_SKEW_S = 60;
const TASK_LEASE_S = 120;
const TASK_MAX_LEASES = 3;
const TASK_WAIT_MAX_S = 60;
const INBOX_WAIT_MAX_S = 25;
const CLASSIFICATIONS = ['public', 'internal', 'restricted', 'prohibited'];
const NODE_ACTIONS = ['restart_agent', 'start_agent', 'stop_agent', 'apply_updates', 'reboot'];

// --------------------------------------------------------------------------
// Keys
// --------------------------------------------------------------------------

/** The raw 32-byte key of an `ssh-ed25519 AAAA… [comment]` line, or null. */
function ssh_ed25519_raw(?string $line): ?string
{
    if (!is_string($line) || !preg_match('/^ssh-ed25519 ([A-Za-z0-9+\/=]+)/', trim($line), $m)) {
        return null;
    }
    $blob = base64_decode($m[1], true);
    if ($blob === false || strlen($blob) < 4 + 11 + 4 + 32) {
        return null;
    }
    // string "ssh-ed25519", string key: both length-prefixed (uint32 big-endian)
    $off = 0;
    $len = unpack('N', substr($blob, $off, 4))[1]; $off += 4;
    if (substr($blob, $off, $len) !== 'ssh-ed25519') { return null; }
    $off += $len;
    $len = unpack('N', substr($blob, $off, 4))[1]; $off += 4;
    if ($len !== 32 || strlen($blob) < $off + 32) { return null; }
    return substr($blob, $off, 32);
}

/** The `ssh-ed25519 …` line of a raw 32-byte public key. */
function ssh_ed25519_line(string $raw, string $comment = ''): string
{
    $blob = pack('N', 11) . 'ssh-ed25519' . pack('N', 32) . $raw;
    return 'ssh-ed25519 ' . base64_encode($blob) . ($comment !== '' ? ' ' . $comment : '');
}

/** The coordinator's key pair, made on first use. @return array{public_key:string, secret:string} (secret = raw 64 bytes) */
function coordinator_key(PDO $pdo): array
{
    $row = $pdo->query('SELECT public_key, secret_key FROM estate_coordinator WHERE id = 1')->fetch();
    if ($row === false) {
        $pair = sodium_crypto_sign_keypair();
        $pub = ssh_ed25519_line(sodium_crypto_sign_publickey($pair), 'coordinator');
        $sec = base64_encode(sodium_crypto_sign_secretkey($pair));
        $pdo->prepare('INSERT INTO estate_coordinator (id, public_key, secret_key) VALUES (1, :p, :s) ON CONFLICT (id) DO NOTHING')->execute(['p' => $pub, 's' => $sec]);
        $row = $pdo->query('SELECT public_key, secret_key FROM estate_coordinator WHERE id = 1')->fetch();
    }
    return ['public_key' => (string) $row['public_key'], 'secret' => (string) base64_decode((string) $row['secret_key'], true)];
}

/** A node reference ("desk:42", "server:57", "inference:3", "coordinator") to [kind, id] or null. */
function node_ref_parse(?string $ref): ?array
{
    if (!is_string($ref)) { return null; }
    if ($ref === 'coordinator') { return ['coordinator', null]; }
    if (preg_match('/^(desk|server|inference):([0-9]{1,12})$/', $ref, $m)) { return [$m[1], (int) $m[2]]; }
    return null;
}

/** The node reference of a locations row. */
function node_ref(array $l): string
{
    return $l['kind'] . ':' . (int) $l['id'];
}

/** The raw public key of a node reference, or null when unknown, retired or keyless. */
function envelope_public_key(PDO $pdo, string $ref): ?string
{
    $p = node_ref_parse($ref);
    if ($p === null) { return null; }
    if ($p[0] === 'coordinator') {
        return ssh_ed25519_raw(coordinator_key($pdo)['public_key']);
    }
    $st = $pdo->prepare("SELECT public_key FROM locations WHERE id = :id AND kind = :kind AND status = 'active'");
    $st->execute(['id' => $p[1], 'kind' => $p[0]]);
    $line = $st->fetchColumn();
    return $line === false ? null : ssh_ed25519_raw((string) $line);
}

/** The keys answer: every active member with a key, and the coordinator's. */
function estate_keys_answer(PDO $pdo): array
{
    $st = $pdo->query("SELECT id, kind, name, public_key, presence FROM locations WHERE kind IN ('desk', 'server', 'inference') AND status = 'active' AND public_key IS NOT NULL ORDER BY kind, id");
    $keys = [];
    foreach ($st->fetchAll() as $l) {
        if (ssh_ed25519_raw((string) $l['public_key']) === null) { continue; }
        $keys[] = ['node' => node_ref($l), 'kind' => (string) $l['kind'], 'name' => (string) $l['name'], 'public_key' => (string) $l['public_key'], 'presence' => (string) $l['presence']];
    }
    return ['ok' => true, 'surface' => DESK_SURFACE, 'coordinator' => ['node' => 'coordinator', 'public_key' => coordinator_key($pdo)['public_key']],
            'keys' => $keys, 'fetched_at' => gmdate('Y-m-d\TH:i:s\Z')];
}

// --------------------------------------------------------------------------
// The envelope: canonical form, signing, verification
// --------------------------------------------------------------------------

/** The canonical value: empty members dropped, keys sorted, recursively. Lists keep their order. */
function envelope_canonical_value(mixed $v): mixed
{
    if (is_array($v)) {
        $isList = array_is_list($v);
        $out = [];
        foreach ($v as $k => $x) {
            $c = envelope_canonical_value($x);
            if ($c === null || $c === []) { continue; }
            $out[$k] = $c;
        }
        if ($isList) { return array_values($out); }
        ksort($out, SORT_STRING);
        return $out;
    }
    return $v;
}

/** The bytes that are signed. */
function envelope_canonical(array $env): string
{
    unset($env['sig']);
    $c = envelope_canonical_value($env);
    if ($c === null || $c === []) { return '{}'; }
    return json_encode($c, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_LINE_TERMINATORS | JSON_THROW_ON_ERROR);
}

/** A new envelope id and nonce. */
function envelope_new_id(): string { return 'env_' . bin2hex(random_bytes(12)); }

/** Sign an envelope as the coordinator (its own agents, decisions it relays). */
function envelope_sign_coordinator(PDO $pdo, array $env): array
{
    $key = coordinator_key($pdo);
    $env['sig'] = ['alg' => 'ed25519', 'key' => 'coordinator', 'value' => base64_encode(sodium_crypto_sign_detached(envelope_canonical($env), $key['secret']))];
    return $env;
}

/** Build an envelope the coordinator originates (e.g. a decision relayed to a node). */
function envelope_make(array $originator, array $sender, array $target, string $purpose, array $authority = [], array $chain = [], ?array $parent = null): array
{
    $now = time();
    $env = ['v' => ENVELOPE_VERSION, 'id' => envelope_new_id(), 'issued_at' => gmdate('Y-m-d\TH:i:s\Z', $now), 'expires_at' => gmdate('Y-m-d\TH:i:s\Z', $now + 600),
            'nonce' => bin2hex(random_bytes(8)), 'originator' => $originator, 'sender' => $sender,
            'chain' => $chain ?: [['principal' => $sender['principal'], 'node' => $sender['node'], 'ts' => gmdate('Y-m-d\TH:i:s\Z', $now), 'task_id' => null]],
            'target' => $target, 'purpose' => $purpose, 'authority' => $authority ?: ['scopes' => [], 'classification' => 'internal', 'budget' => ['usd' => 0, 'calls' => 0]]];
    if ($parent !== null) { $env['parent'] = $parent; }
    return $env;
}

/**
 * Verify an envelope: shape, times, the signature against the directory's key, the sender named by the key,
 * the nonce unseen (recorded now), the parents' signatures. Returns ['ok' => true] or ['ok' => false, 'reason' => …,
 * 'message' => …]. $expectSigner binds the signing key to the caller's token (desk:ID or server:ID).
 */
function envelope_verify(PDO $pdo, mixed $env, ?string $expectSigner = null, bool $consumeNonce = true, int $depth = 0): array
{
    $bad = static fn (string $reason, string $msg) => ['ok' => false, 'reason' => $reason, 'message' => $msg];
    if (!is_array($env) || ($env['v'] ?? null) !== ENVELOPE_VERSION) { return $bad('bad_envelope', 'envelope.v must be ' . ENVELOPE_VERSION . '.'); }
    if ($depth > 8) { return $bad('bad_envelope', 'Too many parents.'); }
    foreach (['id', 'issued_at', 'expires_at', 'nonce'] as $k) {
        if (!is_string($env[$k] ?? null) || $env[$k] === '') { return $bad('bad_envelope', "envelope.$k is required."); }
    }
    if (!preg_match('/^env_[0-9a-f]{12,32}$/', $env['id'])) { return $bad('bad_envelope', 'envelope.id is env_ and hex.'); }
    foreach (['originator', 'sender', 'target', 'sig'] as $k) {
        if (!is_array($env[$k] ?? null)) { return $bad('bad_envelope', "envelope.$k is required."); }
    }
    if (!is_array($env['chain'] ?? null) || $env['chain'] === []) { return $bad('bad_envelope', 'envelope.chain is required.'); }
    $issued = strtotime((string) $env['issued_at']); $expires = strtotime((string) $env['expires_at']);
    if ($issued === false || $expires === false) { return $bad('bad_envelope', 'issued_at and expires_at are ISO-8601 UTC.'); }
    if ($expires - $issued > ENVELOPE_MAX_LIFE_S || $expires < $issued) { return $bad('bad_envelope', 'expires_at is at most an hour after issued_at.'); }
    if ($issued > time() + ENVELOPE_SKEW_S) { return $bad('bad_envelope', 'issued_at is in the future.'); }
    if ($expires < time() - ENVELOPE_SKEW_S) { return $bad('expired', 'The envelope has expired.'); }
    $sig = $env['sig'];
    if (($sig['alg'] ?? null) !== 'ed25519' || !is_string($sig['key'] ?? null) || !is_string($sig['value'] ?? null)) { return $bad('bad_signature', 'sig needs alg ed25519, key and value.'); }
    if (node_ref_parse($sig['key']) === null) { return $bad('bad_signature', 'sig.key names a node (desk:ID, server:ID, inference:ID) or the coordinator.'); }
    if (($env['sender']['node'] ?? null) !== $sig['key']) { return $bad('bad_signature', 'sender.node must be the signing key\'s node.'); }
    if ($expectSigner !== null && $sig['key'] !== $expectSigner) { return $bad('bad_signature', "The caller's token is $expectSigner; the envelope is signed by {$sig['key']}."); }
    $pub = envelope_public_key($pdo, $sig['key']);
    if ($pub === null) { return $bad('bad_signature', "No key is known for {$sig['key']}."); }
    $raw = base64_decode($sig['value'], true);
    if ($raw === false || strlen($raw) !== SODIUM_CRYPTO_SIGN_BYTES || !sodium_crypto_sign_verify_detached($raw, envelope_canonical($env), $pub)) {
        return $bad('bad_signature', 'The signature does not verify.');
    }
    $last = end($env['chain']);
    if (!is_array($last) || ($last['principal'] ?? null) !== ($env['sender']['principal'] ?? '')) { return $bad('bad_envelope', 'The chain\'s last hop is the sender.'); }
    $cls = $env['authority']['classification'] ?? 'internal';
    if (!in_array($cls, CLASSIFICATIONS, true)) { return $bad('bad_envelope', 'authority.classification is public, internal, restricted or prohibited.'); }
    if (isset($env['parent'])) {
        $p = envelope_verify($pdo, $env['parent'], null, false, $depth + 1);
        if (!$p['ok']) { return $bad($p['reason'], 'parent: ' . $p['message']); }
        if (($env['parent']['id'] ?? null) !== $env['id']) { return $bad('bad_envelope', 'A forwarded envelope keeps its parent\'s id.'); }
    }
    if ($consumeNonce) {
        $st = $pdo->prepare('INSERT INTO estate_nonces (key_node, nonce, expires_at) VALUES (:k, :n, to_timestamp(:e)) ON CONFLICT DO NOTHING');
        $st->execute(['k' => $sig['key'], 'n' => mb_substr((string) $env['nonce'], 0, 120), 'e' => $expires + ENVELOPE_SKEW_S]);
        if ($st->rowCount() === 0) { return $bad('replay', 'This nonce was seen before.'); }
    }
    return ['ok' => true];
}

/** Forget nonces past their life (the sweep). */
function envelope_nonce_sweep(PDO $pdo): int
{
    return $pdo->exec('DELETE FROM estate_nonces WHERE expires_at < now()') ?: 0;
}

// --------------------------------------------------------------------------
// The directory
// --------------------------------------------------------------------------

/** A node's manifest list → rows upserted; agents no longer listed are marked removed. @return array{registered:int, removed:int} */
function agents_register(PDO $pdo, array $node, array $list): array
{
    $seen = [];
    $up = $pdo->prepare(<<<'SQL'
        INSERT INTO estate_agents (location_id, name, principal, display_name, description, capabilities, owner, accept_from, max_classification, approve, tasks, unit_state, card, status, last_seen_at, removed_at)
        VALUES (:loc, :name, :principal, :display, :description, :caps, :owner, :accept, :maxc, :approve, :tasks, :unit, :card, 'active', now(), NULL)
        ON CONFLICT (coalesce(location_id, 0), name) DO UPDATE SET
            principal = EXCLUDED.principal, display_name = EXCLUDED.display_name, description = EXCLUDED.description, capabilities = EXCLUDED.capabilities,
            owner = EXCLUDED.owner, accept_from = EXCLUDED.accept_from, max_classification = EXCLUDED.max_classification, approve = EXCLUDED.approve,
            tasks = EXCLUDED.tasks, unit_state = EXCLUDED.unit_state, card = EXCLUDED.card, status = 'active', last_seen_at = now(), removed_at = NULL
    SQL);
    $pgArr = static fn (array $xs) => '{' . implode(',', array_map(static fn ($x) => '"' . str_replace(['\\', '"'], ['\\\\', '\\"'], (string) $x) . '"', $xs)) . '}';
    $tag = static fn (array $xs, string $re) => array_values(array_unique(array_filter(array_map(static fn ($x) => is_string($x) ? strtolower(trim($x)) : '', $xs), static fn ($x) => $x !== '' && preg_match($re, $x))));
    $n = 0;
    foreach ($list as $a) {
        if (!is_array($a) || !is_string($a['name'] ?? null) || !preg_match('/^[a-z][a-z0-9-]{0,30}$/', $a['name'])) { continue; }
        $caps = $tag(is_array($a['capabilities'] ?? null) ? $a['capabilities'] : [], '/^[a-z][a-z0-9._-]{0,40}$/');
        $accept = $tag(is_array($a['accept_from'] ?? null) ? $a['accept_from'] : [], '/^(org|dept:[0-9]+|user:[a-z_][a-z0-9_-]{0,31}|agent:[a-z][a-z0-9-]{0,30}|node:(desk|server|inference))$/');
        $approve = $tag(is_array($a['approve'] ?? null) ? $a['approve'] : [], '/^(public|internal|restricted|prohibited|org|dept:[0-9]+|user:[a-z_][a-z0-9_-]{0,31}|agent:[a-z][a-z0-9-]{0,30}|node:(desk|server|inference))$/');
        $maxc = is_string($a['max_classification'] ?? null) && in_array($a['max_classification'], CLASSIFICATIONS, true) ? $a['max_classification'] : null;
        $up->execute([
            'loc' => (int) $node['id'], 'name' => $a['name'], 'principal' => is_string($a['principal'] ?? null) ? mb_substr($a['principal'], 0, 80) : 'agent:' . $a['name'],
            'display' => is_string($a['display'] ?? null) ? mb_substr(trim($a['display']), 0, 120) : (is_string($a['display_name'] ?? null) ? mb_substr(trim($a['display_name']), 0, 120) : null),
            'description' => is_string($a['description'] ?? null) ? mb_substr(trim($a['description']), 0, 1000) : null,
            'caps' => $pgArr($caps), 'owner' => is_string($a['owner'] ?? null) && $a['owner'] !== '' && $a['owner'] !== 'none' ? mb_substr($a['owner'], 0, 80) : null,
            'accept' => $pgArr($accept), 'maxc' => $maxc, 'approve' => $pgArr($approve),
            'tasks' => (($a['tasks'] ?? true) === false) ? 0 : 1, 'unit' => is_string($a['unit_state'] ?? null) ? mb_substr($a['unit_state'], 0, 20) : (is_string($a['active'] ?? null) ? mb_substr($a['active'], 0, 20) : null),
            'card' => isset($a['card']) && is_array($a['card']) ? json_encode($a['card'], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) : null,
        ]);
        $seen[] = $a['name']; $n++;
    }
    $rm = $pdo->prepare("UPDATE estate_agents SET status = 'removed', removed_at = now() WHERE location_id = :loc AND status = 'active' AND NOT (name = ANY(:seen))");
    $rm->execute(['loc' => (int) $node['id'], 'seen' => $pgArr($seen)]);
    return ['registered' => $n, 'removed' => $rm->rowCount()];
}

/** Every agent of a node marked removed (the node left). */
function agents_deregister(PDO $pdo, int $locationId): int
{
    $st = $pdo->prepare("UPDATE estate_agents SET status = 'removed', removed_at = now() WHERE location_id = :loc AND status = 'active'");
    $st->execute(['loc' => $locationId]);
    return $st->rowCount();
}

/** The directory row with its node, or null. */
function agent_find(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT a.*, l.kind AS node_kind, l.name AS node_name, l.presence AS node_presence, l.status AS node_status, l.enrolled_by_member_id AS node_operator_id
                         FROM estate_agents a LEFT JOIN locations l ON l.id = a.location_id WHERE a.id = :id');
    $st->execute(['id' => $id]);
    $row = $st->fetch();
    return $row === false ? null : $row;
}

/** text[] from PDO ("{a,b}") to a PHP list. */
function pg_text_array(mixed $v): array
{
    if (is_array($v)) { return $v; }
    if (!is_string($v) || $v === '' || $v === '{}') { return []; }
    $out = [];
    foreach (str_getcsv(substr($v, 1, -1), ',', '"', '\\') as $x) { if ($x !== null && $x !== '') { $out[] = (string) $x; } }
    return $out;
}

/** Does the agent's accept_from admit this originator? (empty = its owner only) */
function agent_accepts(PDO $pdo, array $agent, array $originator): bool
{
    $accept = pg_text_array($agent['accept_from'] ?? []);
    $principal = (string) ($originator['principal'] ?? '');
    if ($accept === []) {
        return $principal !== '' && $principal === (string) ($agent['owner'] ?? '');
    }
    $memberId = isset($originator['member_id']) && is_numeric($originator['member_id']) ? (int) $originator['member_id'] : null;
    $onode = node_ref_parse($originator['node'] ?? null);
    foreach ($accept as $rule) {
        if ($rule === 'org' && $memberId !== null) { return true; }
        if ($rule === $principal) { return true; }
        if (str_starts_with($rule, 'node:') && $onode !== null && substr($rule, 5) === $onode[0]) { return true; }
        if (str_starts_with($rule, 'dept:') && $memberId !== null) {
            $st = $pdo->prepare('SELECT 1 FROM department_members WHERE member_id = :m AND department_id = :d');
            $st->execute(['m' => $memberId, 'd' => (int) substr($rule, 5)]);
            if ($st->fetchColumn() !== false) { return true; }
        }
    }
    return false;
}

/** The directory row as the contract presents it. */
function present_agent(array $a): array
{
    $node = $a['location_id'] !== null
        ? ['id' => (int) $a['location_id'], 'kind' => (string) $a['node_kind'], 'name' => (string) $a['node_name'], 'presence' => (string) $a['node_presence'], 'ref' => $a['node_kind'] . ':' . (int) $a['location_id']]
        : ['id' => null, 'kind' => 'coordinator', 'name' => 'coordinator', 'presence' => 'online', 'ref' => 'coordinator'];
    $card = is_string($a['card'] ?? null) ? (json_decode($a['card'], true) ?: null) : ($a['card'] ?? null);
    return [
        'id' => (int) $a['id'], 'name' => (string) $a['name'], 'principal' => (string) $a['principal'],
        'display_name' => $a['display_name'] ?? null, 'description' => $a['description'] ?? '',
        'capabilities' => pg_text_array($a['capabilities']), 'owner' => $a['owner'] ?? null,
        'accept_from' => pg_text_array($a['accept_from']), 'max_classification' => $a['max_classification'] ?? null, 'approve' => pg_text_array($a['approve'] ?? []),
        'node' => $node, 'status' => (string) $a['status'], 'unit_state' => $a['unit_state'] ?? null,
        'presence' => $a['status'] !== 'active' ? 'removed' : ($node['presence'] === 'online' && ($a['unit_state'] ?? 'active') === 'active' ? 'online' : 'offline'),
        'state' => ($a['unit_state'] ?? null) === 'failed' ? 'failed' : 'idle',
        'tasks' => !empty($a['tasks']) && $a['status'] === 'active' ? app_url('/api/v1/estate/agents/' . (int) $a['id'] . '/tasks') : null,
        'card' => $card, 'hired' => $a['agent_member_id'] !== null, 'first_seen_at' => json_ts($a['first_seen_at'] ?? null), 'last_seen_at' => json_ts($a['last_seen_at'] ?? null),
    ];
}

/** The directory answer: active agents, by capability and/or node. */
function estate_agents_answer(PDO $pdo, ?string $capability = null, ?int $locationId = null, bool $includeRemoved = false): array
{
    $sql = 'SELECT a.*, l.kind AS node_kind, l.name AS node_name, l.presence AS node_presence, l.status AS node_status, l.enrolled_by_member_id AS node_operator_id
            FROM estate_agents a LEFT JOIN locations l ON l.id = a.location_id WHERE ' . ($includeRemoved ? 'true' : "a.status = 'active'");
    $p = [];
    if ($capability !== null && $capability !== '') { $sql .= ' AND :cap = ANY(a.capabilities)'; $p['cap'] = strtolower($capability); }
    if ($locationId !== null) { $sql .= ' AND a.location_id = :loc'; $p['loc'] = $locationId; }
    $sql .= ' ORDER BY l.name NULLS FIRST, a.name';
    $st = $pdo->prepare($sql); $st->execute($p);
    return ['ok' => true, 'surface' => DESK_SURFACE, 'agents' => array_map('present_agent', $st->fetchAll()), 'fetched_at' => gmdate('Y-m-d\TH:i:s\Z')];
}

/** The first active agent with a capability whose policy admits the originator, preferring an online node. */
function agent_resolve_capability(PDO $pdo, string $capability, array $originator): ?array
{
    $st = $pdo->prepare("SELECT a.*, l.kind AS node_kind, l.name AS node_name, l.presence AS node_presence, l.status AS node_status, l.enrolled_by_member_id AS node_operator_id
                         FROM estate_agents a LEFT JOIN locations l ON l.id = a.location_id
                         WHERE a.status = 'active' AND a.tasks AND :cap = ANY(a.capabilities) AND a.location_id IS NOT NULL
                         ORDER BY (l.presence = 'online') DESC, (a.unit_state = 'active') DESC, a.last_seen_at DESC");
    $st->execute(['cap' => strtolower($capability)]);
    foreach ($st->fetchAll() as $a) {
        if (agent_accepts($pdo, $a, $originator)) { return $a; }
    }
    return null;
}

// --------------------------------------------------------------------------
// Tasks
// --------------------------------------------------------------------------

function task_new_id(): string { return 't_' . bin2hex(random_bytes(8)); }

/** The caller's node reference and originator binding from an authenticated context (desk or node). */
function caller_node_ref(array $ctx): string
{
    return isset($ctx['desk']) ? 'desk:' . (int) $ctx['desk']['id'] : node_ref($ctx['node']);
}

/**
 * Store a task for an agent from a verified envelope: idempotent on (envelope id, hop). Returns the row.
 * The originator member is the desk's owner when a desk sent it (the token binds them), else the envelope's claim
 * only when it names a member whose desk signed a parent — otherwise null.
 */
function task_create(PDO $pdo, array $agent, array $env, array $message, array $ctx): array
{
    $hop = max(1, count($env['chain']));
    $st = $pdo->prepare('SELECT * FROM estate_tasks WHERE envelope_id = :e AND hop = :h');
    $st->execute(['e' => $env['id'], 'h' => $hop]);
    $existing = $st->fetch();
    if ($existing !== false) { return $existing; }
    $originatorMember = isset($ctx['desk']) ? (int) $ctx['member']['id'] : null;
    if ($originatorMember === null) {
        // a node sent it: the originator's member is the owner of the desk that signed the root of the parent chain
        // (every parent's signature was verified), else the envelope's claim when that member owns the originator's desk
        $root = $env;
        while (is_array($root['parent'] ?? null)) { $root = $root['parent']; }
        $rk = node_ref_parse($root['sig']['key'] ?? null);
        if ($rk !== null && $rk[0] === 'desk' && $root !== $env) {
            $q = $pdo->prepare("SELECT owner_member_id FROM locations WHERE id = :id AND kind = 'desk'");
            $q->execute(['id' => $rk[1]]);
            $m = $q->fetchColumn();
            $originatorMember = $m !== false && $m !== null ? (int) $m : null;
        } elseif (is_numeric($env['originator']['member_id'] ?? null)) {
            $on = node_ref_parse($env['originator']['node'] ?? null);
            $q = $pdo->prepare("SELECT 1 FROM locations WHERE id = :id AND kind = 'desk' AND owner_member_id = :m");
            $q->execute(['id' => $on !== null && $on[0] === 'desk' ? $on[1] : 0, 'm' => (int) $env['originator']['member_id']]);
            $originatorMember = $q->fetchColumn() !== false ? (int) $env['originator']['member_id'] : null;
        }
    }
    $id = task_new_id();
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO estate_tasks (id, envelope_id, hop, agent_id, location_id, originator_principal, originator_member_id, sender_principal, sender_node, envelope, message, state)
        VALUES (:id, :eid, :hop, :agent, :loc, :op, :om, :sp, :sn, :env, :msg, 'queued')
    SQL);
    $st->execute(['id' => $id, 'eid' => $env['id'], 'hop' => $hop, 'agent' => (int) $agent['id'], 'loc' => $agent['location_id'] !== null ? (int) $agent['location_id'] : null,
                  'op' => mb_substr((string) ($env['originator']['principal'] ?? ''), 0, 120), 'om' => $originatorMember,
                  'sp' => mb_substr((string) ($env['sender']['principal'] ?? ''), 0, 120), 'sn' => (string) $env['sender']['node'],
                  'env' => json_encode($env, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE), 'msg' => json_encode($message, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)]);
    if ($agent['location_id'] !== null) { node_notify($pdo, (int) $agent['location_id']); }
    return task_row($pdo, $id);
}

function task_row(PDO $pdo, string $id): array
{
    $st = $pdo->prepare('SELECT t.*, a.name AS agent_name, a.principal AS agent_principal, l.kind AS node_kind, l.name AS node_name
                         FROM estate_tasks t JOIN estate_agents a ON a.id = t.agent_id LEFT JOIN locations l ON l.id = t.location_id WHERE t.id = :id');
    $st->execute(['id' => $id]);
    $row = $st->fetch();
    return $row === false ? [] : $row;
}

/** The task record in the task interface's shape (slice 8), with provenance and usage from the node's result. */
function present_task(array $t): array
{
    $msg = is_string($t['message']) ? (json_decode($t['message'], true) ?: []) : ($t['message'] ?? []);
    $res = is_string($t['result'] ?? null) ? (json_decode($t['result'], true) ?: []) : ($t['result'] ?? []);
    $parts = is_array($msg['parts'] ?? null) ? $msg['parts'] : [];
    $text = trim(implode(' ', array_map(static fn ($p) => is_array($p) ? (string) ($p['text'] ?? '') : '', $parts)));
    $node = $t['location_id'] !== null ? $t['node_kind'] . ':' . (int) $t['location_id'] : 'coordinator';
    $state = (string) $t['state'];
    return [
        'id' => (string) $t['id'], 'state' => $state === 'leased' ? 'queued' : $state, 'ts' => json_ts($t['created_at']),
        'input' => ['text' => $text, 'parts' => $parts], 'output' => $res['output'] ?? null,
        'error' => $res['error'] ?? ($state === 'refused' || $state === 'failed' ? ($t['reason'] ?? $state) : null), 'done_ts' => json_ts($t['done_at'] ?? null),
        'envelope_id' => (string) $t['envelope_id'], 'hop' => (int) $t['hop'],
        'agent' => ['id' => (int) $t['agent_id'], 'name' => (string) $t['agent_name'], 'principal' => (string) $t['agent_principal']],
        'node' => $node, 'originator' => (string) $t['originator_principal'], 'sender' => ['principal' => (string) $t['sender_principal'], 'node' => (string) $t['sender_node']],
        'reason' => $t['reason'] ?? null, 'leases' => (int) $t['leases'],
        'provenance' => $res['provenance'] ?? null, 'usage' => $res['usage'] ?? null, 'ask' => $state === 'pending_approval' ? ($res['ask'] ?? null) : null,
    ];
}

/** Wait for a task to leave the queue (tasks/send with wait): polls the row, up to TASK_WAIT_MAX_S. */
function task_wait(PDO $pdo, string $id, float $timeout): array
{
    $deadline = microtime(true) + min(max($timeout, 0.0), TASK_WAIT_MAX_S);
    $t = task_row($pdo, $id);
    while (in_array($t['state'] ?? '', ['queued', 'leased', 'running'], true) && microtime(true) < $deadline) {
        usleep(300000);
        $t = task_row($pdo, $id);
    }
    return $t;
}

/** May this caller read the task? The originator, the sender, the agent's node, an operator. */
function task_visible(array $t, array $ctx): bool
{
    if (isset($ctx['node'])) {
        return (int) ($t['location_id'] ?? 0) === (int) $ctx['node']['id'] || $t['sender_node'] === node_ref($ctx['node']);
    }
    if (estate_operator($ctx['member'] ?? null)) { return true; }
    return (int) ($t['originator_member_id'] ?? 0) === (int) $ctx['member']['id'] || $t['sender_node'] === caller_node_ref($ctx);
}

/** The JSON-RPC methods of an estate agent (agent/card, tasks/send, tasks/get, tasks/list) for a desk or node caller. @return array{result?:mixed, error?:array} */
function agent_rpc(PDO $pdo, array $agent, array $req, array $ctx): array
{
    $err = static fn (int $code, string $msg, ?string $reason = null) => ['error' => ['code' => $code, 'message' => $msg] + ($reason !== null ? ['data' => ['reason' => $reason]] : [])];
    $method = $req['method'] ?? null; $params = is_array($req['params'] ?? null) ? $req['params'] : [];
    if ($method === 'agent/card') {
        $p = present_agent($agent);
        return ['result' => ($p['card'] ?? []) + ['name' => $p['display_name'] ?? $p['name'], 'description' => $p['description'], 'capabilities' => $p['capabilities'],
                 'principal' => $p['principal'], 'owner' => $p['owner'], 'node' => $p['node']['ref'], 'accept_from' => $p['accept_from'], 'protocol' => 'maluos-tasks/0.3']];
    }
    if ($method === 'tasks/send') {
        if ($agent['status'] !== 'active' || empty($agent['tasks'])) { return $err(-32004, 'This agent takes no tasks.', 'not_available'); }
        if ($agent['location_id'] === null) { return $err(-32004, "The coordinator's own agents take tasks through the office's chat endpoint; the directory lists them for their capabilities.", 'not_supported'); }
        $msg = is_array($params['message'] ?? null) ? $params['message'] : [];
        $parts = is_array($msg['parts'] ?? null) ? $msg['parts'] : (is_string($params['text'] ?? null) && $params['text'] !== '' ? [['type' => 'text', 'text' => $params['text']]] : []);
        $text = trim(implode(' ', array_map(static fn ($p) => is_array($p) && ($p['type'] ?? 'text') === 'text' ? (string) ($p['text'] ?? '') : '', $parts)));
        if ($text === '') { return $err(-32602, 'tasks/send needs message.parts with text'); }
        if (strlen(json_encode($parts) ?: '') > 65536) { return $err(-32602, 'The message is over 64 KB.'); }
        $env = $params['envelope'] ?? null;
        if (!is_array($env)) { return $err(-32602, 'tasks/send to an estate agent needs an envelope (docs/phase13-slice2-delegation.md).', 'envelope_required'); }
        $v = envelope_verify($pdo, $env, caller_node_ref($ctx));
        if (!$v['ok']) { return $err(-32001, $v['message'], $v['reason']); }
        $tgt = $env['target'];
        if (isset($tgt['agent']) && $tgt['agent'] !== $agent['name']) { return $err(-32602, 'envelope.target.agent is not this agent.', 'bad_envelope'); }
        if (isset($tgt['node']) && $tgt['node'] !== present_agent($agent)['node']['ref']) { return $err(-32602, 'envelope.target.node is not this agent\'s node.', 'bad_envelope'); }
        $t = task_create($pdo, $agent, $env, ['role' => $msg['role'] ?? 'user', 'parts' => $parts], $ctx);
        log_activity($pdo, 'estate.task.send', 'estate_task', null, ['source' => isset($ctx['desk']) ? 'desk' : 'node',
            'after' => ['task' => $t['id'], 'envelope' => $env['id'], 'agent' => $agent['name'], 'node' => present_agent($agent)['node']['ref'], 'originator' => $t['originator_principal'], 'purpose' => mb_substr((string) ($env['purpose'] ?? ''), 0, 200)]]);
        if (($params['wait'] ?? true) !== false) { $t = task_wait($pdo, $t['id'], (float) ($params['timeout'] ?? 30)); }
        return ['result' => present_task($t)];
    }
    if ($method === 'tasks/get') {
        $t = is_string($params['id'] ?? null) ? task_row($pdo, $params['id']) : [];
        if ($t === [] || (int) $t['agent_id'] !== (int) $agent['id'] || !task_visible($t, $ctx)) { return $err(-32004, 'no such task'); }
        if (($params['wait'] ?? false) && in_array($t['state'], ['queued', 'leased', 'running'], true)) { $t = task_wait($pdo, $t['id'], (float) ($params['timeout'] ?? 30)); }
        return ['result' => present_task($t)];
    }
    if ($method === 'tasks/list') {
        $st = $pdo->prepare('SELECT t.*, a.name AS agent_name, a.principal AS agent_principal, l.kind AS node_kind, l.name AS node_name FROM estate_tasks t JOIN estate_agents a ON a.id = t.agent_id
                             LEFT JOIN locations l ON l.id = t.location_id WHERE t.agent_id = :a ORDER BY t.created_at DESC LIMIT 200');
        $st->execute(['a' => (int) $agent['id']]);
        $rows = array_values(array_filter($st->fetchAll(), static fn ($t) => task_visible($t, $ctx)));
        return ['result' => ['tasks' => array_map('present_task', array_slice($rows, 0, max(1, min(200, (int) ($params['limit'] ?? 50)))))]];
    }
    return $err(-32601, 'unknown method ' . (is_string($method) ? $method : '?'));
}

// --------------------------------------------------------------------------
// The node's inbox: tasks and actions, leased
// --------------------------------------------------------------------------

function node_channel(int $locationId): string { return 'estate_node_' . $locationId; }
function member_channel(int $memberId): string { return 'estate_member_' . $memberId; }

function node_notify(PDO $pdo, int $locationId): void
{
    try { $pdo->exec('NOTIFY ' . node_channel($locationId)); } catch (Throwable) {}
}

function member_notify(PDO $pdo, int $memberId): void
{
    try { $pdo->exec('NOTIFY ' . member_channel($memberId)); } catch (Throwable) {}
}

/** Leases past their time go back to the queue; three leases and it failed (node_unresponsive). @return int rows touched */
function lease_sweep(PDO $pdo): int
{
    $n = 0;
    foreach (['estate_tasks', 'estate_actions'] as $tbl) {
        $n += $pdo->exec("UPDATE $tbl SET state = 'failed', reason = 'node_unresponsive', done_at = now() WHERE state = 'leased' AND lease_until < now() AND leases >= " . TASK_MAX_LEASES) ?: 0;
        $n += $pdo->exec("UPDATE $tbl SET state = 'queued', lease_until = NULL WHERE state = 'leased' AND lease_until < now()") ?: 0;
    }
    return $n;
}

/** Take the queued items of a node, leasing them. @return array<int,array> */
function inbox_take(PDO $pdo, int $locationId): array
{
    $items = [];
    $pdo->beginTransaction();
    try {
        $st = $pdo->prepare("UPDATE estate_tasks SET state = 'leased', lease_until = now() + make_interval(secs => :lease), leases = leases + 1
                             WHERE id IN (SELECT id FROM estate_tasks WHERE location_id = :loc AND state = 'queued' ORDER BY created_at LIMIT 20 FOR UPDATE SKIP LOCKED)
                             RETURNING id");
        $st->execute(['loc' => $locationId, 'lease' => TASK_LEASE_S]);
        foreach ($st->fetchAll(PDO::FETCH_COLUMN) as $id) {
            $t = task_row($pdo, (string) $id);
            $res = is_string($t['result'] ?? null) ? (json_decode($t['result'], true) ?: []) : [];
            $items[] = ['id' => (string) $t['id'], 'kind' => 'task', 'agent' => (string) $t['agent_name'], 'envelope' => json_decode((string) $t['envelope'], true),
                        'message' => json_decode((string) $t['message'], true), 'answer' => $res['answer'] ?? null, 'lease_until' => json_ts($t['lease_until']), 'leases' => (int) $t['leases']];
        }
        $st = $pdo->prepare("UPDATE estate_actions SET state = 'leased', lease_until = now() + make_interval(secs => :lease), leases = leases + 1
                             WHERE id IN (SELECT id FROM estate_actions WHERE location_id = :loc AND state = 'queued' ORDER BY created_at LIMIT 20 FOR UPDATE SKIP LOCKED)
                             RETURNING id, action, agent, envelope, lease_until, leases");
        $st->execute(['loc' => $locationId, 'lease' => TASK_LEASE_S]);
        foreach ($st->fetchAll() as $a) {
            $items[] = ['id' => (string) $a['id'], 'kind' => 'action', 'action' => (string) $a['action'], 'agent' => $a['agent'], 'envelope' => json_decode((string) $a['envelope'], true),
                        'lease_until' => json_ts($a['lease_until']), 'leases' => (int) $a['leases']];
        }
        $pdo->commit();
    } catch (Throwable $e) {
        $pdo->rollBack(); throw $e;
    }
    return $items;
}

/** Long-poll a channel: LISTEN, then wait up to $wait seconds for a notification (or return at once when $wait is 0). */
function channel_wait(PDO $pdo, string $channel, float $wait): bool
{
    if ($wait <= 0) { return false; }
    try {
        $pdo->exec('LISTEN ' . $channel);
        $n = $pdo->pgsqlGetNotify(PDO::FETCH_ASSOC, (int) ($wait * 1000));
        $pdo->exec('UNLISTEN ' . $channel);
        return $n !== false;
    } catch (Throwable) {
        usleep((int) (min($wait, 2.0) * 1000000));
        return false;
    }
}

/** The node's inbox answer: items leased to it, waiting up to $wait seconds for one. */
function node_inbox_answer(PDO $pdo, array $node, float $wait): array
{
    $wait = min(max($wait, 0.0), INBOX_WAIT_MAX_S);
    lease_sweep($pdo);
    $items = inbox_take($pdo, (int) $node['id']);
    if ($items === [] && $wait > 0) {
        $deadline = microtime(true) + $wait;
        $pdo->exec('LISTEN ' . node_channel((int) $node['id']));
        try {
            while ($items === [] && microtime(true) < $deadline) {
                $left = $deadline - microtime(true);
                try { $pdo->pgsqlGetNotify(PDO::FETCH_ASSOC, (int) (min($left, 2.0) * 1000)); } catch (Throwable) { usleep((int) (min($left, 2.0) * 1000000)); }
                $items = inbox_take($pdo, (int) $node['id']);
            }
        } finally {
            try { $pdo->exec('UNLISTEN ' . node_channel((int) $node['id'])); } catch (Throwable) {}
        }
    }
    return ['ok' => true, 'surface' => DESK_SURFACE, 'items' => $items, 'lease_s' => TASK_LEASE_S, 'fetched_at' => gmdate('Y-m-d\TH:i:s\Z')];
}

/**
 * The node's result for an item: a task record (state completed|failed|refused|pending_approval, with output,
 * provenance, usage, error, ask) or an action's outcome ({ok, state, output, error}). @return array the item's answer
 */
function inbox_result(PDO $pdo, array $node, string $itemId, array $body): array
{
    $res = is_array($body['result'] ?? null) ? $body['result'] : [];
    if (str_starts_with($itemId, 't_')) {
        $t = task_row($pdo, $itemId);
        if ($t === [] || (int) $t['location_id'] !== (int) $node['id']) { api_error('not_found', 'No such task of this node.', 404); }
        if (in_array($t['state'], ['completed', 'failed', 'refused'], true)) { return ['ok' => true, 'task' => present_task($t), 'note' => 'already done']; }
        $state = (string) ($res['state'] ?? ($body['refused'] ?? null ? 'refused' : 'failed'));
        $reason = is_string($body['refused'] ?? null) ? $body['refused'] : (is_string($res['reason'] ?? null) ? $res['reason'] : null);
        if (!in_array($state, ['completed', 'failed', 'refused', 'pending_approval', 'working', 'running'], true)) { $state = 'failed'; }
        if ($state === 'working') { $state = 'running'; }
        if (strlen(json_encode($res) ?: '') > 262144) { api_error('invalid', 'The result is over 256 KB.', 400); }
        $keep = array_intersect_key($res, array_flip(['output', 'error', 'provenance', 'usage', 'ask', 'answer']));
        if ($state === 'pending_approval') {
            $ask = is_array($res['ask'] ?? null) ? $res['ask'] : [];
            $approver = $t['originator_member_id'] !== null ? (int) $t['originator_member_id'] : (int) ($node['enrolled_by_member_id'] ?? 0);
            if ($approver > 0) {
                inbox_post($pdo, $approver, (string) ($ask['kind'] ?? 'decision_needed') === 'question' ? 'question' : 'decision_needed',
                    mb_substr((string) ($ask['subject'] ?? ("{$t['agent_name']} asks to run a task")), 0, 300), (string) ($ask['body'] ?? ''),
                    (string) $t['agent_principal'], node_ref($node), (string) $t['id'], is_array($ask['options'] ?? null) ? $ask['options'] : ['approve', 'deny']);
            } else {
                $state = 'failed'; $reason = 'no_approver';
            }
        }
        $st = $pdo->prepare("UPDATE estate_tasks SET state = :s, reason = :r, result = :res, lease_until = NULL,
                             started_at = coalesce(started_at, now()), done_at = CASE WHEN :s2 IN ('completed','failed','refused') THEN now() ELSE NULL END WHERE id = :id");
        $st->execute(['s' => $state, 's2' => $state, 'r' => $reason !== null ? mb_substr($reason, 0, 200) : null, 'id' => $itemId,
                      'res' => json_encode($keep, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)]);
        $t = task_row($pdo, $itemId);
        if (in_array($state, ['completed', 'failed', 'refused'], true)) {
            log_activity($pdo, 'estate.task.' . $state, 'estate_task', null, ['source' => 'node', 'after' => ['task' => $t['id'], 'envelope' => $t['envelope_id'], 'agent' => $t['agent_name'], 'node' => node_ref($node), 'reason' => $reason]]);
            if ($t['originator_member_id'] !== null && $state !== 'completed') {
                inbox_post($pdo, (int) $t['originator_member_id'], 'fyi', mb_substr("{$t['agent_name']} {$state}: " . ($reason ?: ($keep['error'] ?? 'the task did not complete')), 0, 300), '', (string) $t['agent_principal'], node_ref($node), (string) $t['id']);
            }
        }
        return ['ok' => true, 'task' => present_task($t)];
    }
    if (str_starts_with($itemId, 'a_')) {
        $st = $pdo->prepare('SELECT * FROM estate_actions WHERE id = :id'); $st->execute(['id' => $itemId]);
        $a = $st->fetch();
        if ($a === false || (int) $a['location_id'] !== (int) $node['id']) { api_error('not_found', 'No such action of this node.', 404); }
        if (in_array($a['state'], ['completed', 'failed', 'refused'], true)) { return ['ok' => true, 'action' => present_action($a), 'note' => 'already done']; }
        $state = (string) ($res['state'] ?? (($res['ok'] ?? false) ? 'completed' : (isset($body['refused']) ? 'refused' : 'failed')));
        if (!in_array($state, ['completed', 'failed', 'refused'], true)) { $state = 'failed'; }
        $reason = is_string($body['refused'] ?? null) ? $body['refused'] : (is_string($res['reason'] ?? null) ? $res['reason'] : (is_string($res['error'] ?? null) ? $res['error'] : null));
        $st = $pdo->prepare("UPDATE estate_actions SET state = :s, reason = :r, result = :res, lease_until = NULL, done_at = now() WHERE id = :id");
        $st->execute(['s' => $state, 'r' => $reason !== null ? mb_substr($reason, 0, 200) : null, 'id' => $itemId, 'res' => json_encode(array_intersect_key($res, array_flip(['ok', 'output', 'error', 'state'])), JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)]);
        $st = $pdo->prepare('SELECT * FROM estate_actions WHERE id = :id'); $st->execute(['id' => $itemId]);
        $a = $st->fetch();
        log_activity($pdo, 'estate.action.' . $state, 'location', (int) $node['id'], ['source' => 'node', 'after' => ['action' => $a['action'], 'agent' => $a['agent'], 'id' => $a['id'], 'reason' => $reason]]);
        inbox_post($pdo, (int) $a['requested_by_member_id'], 'result', mb_substr("{$a['action']}" . ($a['agent'] ? " {$a['agent']}" : '') . " on {$node['name']}: {$state}" . ($reason ? " ({$reason})" : ''), 0, 300),
                   is_string($res['output'] ?? null) ? mb_substr($res['output'], 0, 4000) : '', 'node', node_ref($node));
        return ['ok' => true, 'action' => present_action($a)];
    }
    api_error('not_found', 'An item id is t_… or a_….', 404);
}

// --------------------------------------------------------------------------
// Actions on a node
// --------------------------------------------------------------------------

function present_action(array $a): array
{
    $res = is_string($a['result'] ?? null) ? (json_decode($a['result'], true) ?: null) : ($a['result'] ?? null);
    return ['id' => (string) $a['id'], 'node' => ['id' => (int) $a['location_id'], 'name' => $a['node_name'] ?? null], 'action' => (string) $a['action'], 'agent' => $a['agent'] ?? null,
            'state' => (string) $a['state'], 'reason' => $a['reason'] ?? null, 'result' => $res, 'requested_by' => (int) $a['requested_by_member_id'],
            'envelope_id' => json_decode((string) $a['envelope'], true)['id'] ?? null, 'created_at' => json_ts($a['created_at']), 'done_at' => json_ts($a['done_at'] ?? null)];
}

/** Queue an operator's action on a node with its verified envelope. */
function action_create(PDO $pdo, array $node, string $action, ?string $agent, array $env, array $ctx): array
{
    if (!in_array($action, NODE_ACTIONS, true)) { api_error('invalid', 'action is one of ' . implode(', ', NODE_ACTIONS) . '.', 400); }
    if (str_ends_with($action, '_agent') && (!is_string($agent) || !preg_match('/^[a-z][a-z0-9-]{0,30}$/', $agent))) { api_error('invalid', 'The agent actions need agent.', 400); }
    $v = envelope_verify($pdo, $env, caller_node_ref($ctx));
    if (!$v['ok']) { api_error($v['reason'], $v['message'], 403); }
    if (($env['target']['node'] ?? null) !== node_ref($node)) { api_error('bad_envelope', 'envelope.target.node is not this node.', 400); }
    $id = 'a_' . bin2hex(random_bytes(8));
    $st = $pdo->prepare('INSERT INTO estate_actions (id, location_id, action, agent, envelope, requested_by_member_id) VALUES (:id, :loc, :a, :ag, :env, :m)');
    $st->execute(['id' => $id, 'loc' => (int) $node['id'], 'a' => $action, 'ag' => str_ends_with($action, '_agent') ? $agent : null,
                  'env' => json_encode($env, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE), 'm' => (int) $ctx['member']['id']]);
    node_notify($pdo, (int) $node['id']);
    log_activity($pdo, 'estate.action.request', 'location', (int) $node['id'], ['source' => 'desk', 'after' => ['action' => $action, 'agent' => $agent, 'id' => $id, 'envelope' => $env['id']]]);
    return action_row($pdo, $id);
}

function action_row(PDO $pdo, string $id): array
{
    $st = $pdo->prepare('SELECT a.*, l.name AS node_name FROM estate_actions a JOIN locations l ON l.id = a.location_id WHERE a.id = :id');
    $st->execute(['id' => $id]);
    $row = $st->fetch();
    return $row === false ? [] : $row;
}

/** Wait for an action to finish, up to $timeout seconds. */
function action_wait(PDO $pdo, string $id, float $timeout): array
{
    $deadline = microtime(true) + min(max($timeout, 0.0), TASK_WAIT_MAX_S);
    $a = action_row($pdo, $id);
    while (in_array($a['state'] ?? '', ['queued', 'leased'], true) && microtime(true) < $deadline) {
        usleep(300000);
        $a = action_row($pdo, $id);
    }
    return $a;
}

// --------------------------------------------------------------------------
// The person's estate inbox
// --------------------------------------------------------------------------

function inbox_post(PDO $pdo, int $memberId, string $kind, string $subject, string $body, string $fromPrincipal, string $fromNode, ?string $taskId = null, ?array $options = null): int
{
    $st = $pdo->prepare('INSERT INTO estate_inbox (member_id, kind, subject, body, from_principal, from_node, task_id, options) VALUES (:m, :k, :s, :b, :fp, :fn, :t, :o) RETURNING id');
    $st->execute(['m' => $memberId, 'k' => $kind, 's' => mb_substr($subject !== '' ? $subject : '(no subject)', 0, 300), 'b' => mb_substr($body, 0, 20000), 'fp' => mb_substr($fromPrincipal, 0, 120), 'fn' => mb_substr($fromNode, 0, 40),
                  't' => $taskId, 'o' => $options !== null ? '{' . implode(',', array_map(static fn ($x) => '"' . str_replace('"', '', (string) $x) . '"', $options)) . '}' : null]);
    $id = (int) $st->fetchColumn();
    member_notify($pdo, $memberId);
    return $id;
}

function present_inbox_item(array $i): array
{
    return ['id' => (int) $i['id'], 'kind' => (string) $i['kind'], 'subject' => (string) $i['subject'], 'body' => (string) $i['body'],
            'from' => ['principal' => (string) $i['from_principal'], 'node' => (string) $i['from_node']], 'task_id' => $i['task_id'] ?? null,
            'options' => $i['options'] !== null ? pg_text_array($i['options']) : null, 'status' => (string) $i['status'],
            'decision' => $i['decision'] ?? null, 'decision_note' => $i['decision_note'] ?? null, 'reply' => $i['reply'] ?? null,
            'created_at' => json_ts($i['created_at']), 'read_at' => json_ts($i['read_at'] ?? null), 'done_at' => json_ts($i['done_at'] ?? null)];
}

/** The desk's inbox: unread (and, with all, the last 50) items, waiting up to $wait seconds for a new one. */
function desk_inbox_answer(PDO $pdo, array $member, float $wait, bool $all = false, int $sinceId = 0): array
{
    $wait = min(max($wait, 0.0), INBOX_WAIT_MAX_S);
    $fetch = static function () use ($pdo, $member, $all, $sinceId): array {
        $st = $pdo->prepare('SELECT * FROM estate_inbox WHERE member_id = :m AND id > :since' . ($all ? '' : " AND status = 'unread'") . ' ORDER BY created_at DESC, id DESC LIMIT 50');
        $st->execute(['m' => (int) $member['id'], 'since' => $sinceId]);
        return $st->fetchAll();
    };
    $rows = $fetch();
    if ($rows === [] && $wait > 0) {
        $deadline = microtime(true) + $wait;
        $pdo->exec('LISTEN ' . member_channel((int) $member['id']));
        try {
            while ($rows === [] && microtime(true) < $deadline) {
                $left = $deadline - microtime(true);
                try { $pdo->pgsqlGetNotify(PDO::FETCH_ASSOC, (int) (min($left, 2.0) * 1000)); } catch (Throwable) { usleep((int) (min($left, 2.0) * 1000000)); }
                $rows = $fetch();
            }
        } finally {
            try { $pdo->exec('UNLISTEN ' . member_channel((int) $member['id'])); } catch (Throwable) {}
        }
    }
    $st = $pdo->prepare("SELECT count(*) FROM estate_inbox WHERE member_id = :m AND status = 'unread'");
    $st->execute(['m' => (int) $member['id']]);
    return ['ok' => true, 'surface' => DESK_SURFACE, 'unread' => (int) $st->fetchColumn(), 'items' => array_map('present_inbox_item', $rows), 'fetched_at' => gmdate('Y-m-d\TH:i:s\Z')];
}

/** How many unread items a person has (the heartbeat's hint). */
function inbox_unread(PDO $pdo, int $memberId): int
{
    $st = $pdo->prepare("SELECT count(*) FROM estate_inbox WHERE member_id = :m AND status = 'unread'");
    $st->execute(['m' => $memberId]);
    return (int) $st->fetchColumn();
}

/**
 * The person's reply or decision on an item, with their desk's envelope (signed by the desk key, target the
 * asking node): recorded, and the parked task re-queued to its node with the answer.
 */
function inbox_answer(PDO $pdo, array $member, int $itemId, string $what, array $body, array $ctx): array
{
    $st = $pdo->prepare('SELECT * FROM estate_inbox WHERE id = :id AND member_id = :m'); $st->execute(['id' => $itemId, 'm' => (int) $member['id']]);
    $item = $st->fetch();
    if ($item === false) { api_error('not_found', 'No such inbox item of yours.', 404); }
    if ($item['status'] === 'done') { api_error('conflict', 'This item was answered already.', 409); }
    $env = $body['envelope'] ?? null;
    if (!is_array($env)) { api_error('envelope_required', 'A reply or decision carries the desk\'s envelope.', 400); }
    $v = envelope_verify($pdo, $env, caller_node_ref($ctx));
    if (!$v['ok']) { api_error($v['reason'], $v['message'], 403); }
    $decision = null; $note = null; $reply = null;
    if ($what === 'decide') {
        $decision = is_string($body['decision'] ?? null) ? strtolower(trim($body['decision'])) : '';
        $options = $item['options'] !== null ? pg_text_array($item['options']) : ['approve', 'deny'];
        if (!in_array($decision, $options, true)) { api_error('invalid', 'decision is one of ' . implode(', ', $options) . '.', 400); }
        $note = is_string($body['note'] ?? null) ? mb_substr($body['note'], 0, 2000) : null;
    } else {
        $reply = is_string($body['text'] ?? null) ? mb_substr(trim($body['text']), 0, 20000) : '';
        if ($reply === '') { api_error('invalid', 'text is required.', 400); }
    }
    $st = $pdo->prepare("UPDATE estate_inbox SET status = 'done', decision = :d, decision_note = :n, reply = :r, answer_envelope = :e, read_at = coalesce(read_at, now()), done_at = now() WHERE id = :id");
    $st->execute(['d' => $decision, 'n' => $note, 'r' => $reply, 'e' => json_encode($env, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE), 'id' => $itemId]);
    $task = null;
    if ($item['task_id'] !== null) {
        $t = task_row($pdo, (string) $item['task_id']);
        if ($t !== [] && $t['state'] === 'pending_approval') {
            $res = is_string($t['result'] ?? null) ? (json_decode($t['result'], true) ?: []) : [];
            $res['answer'] = ['kind' => $what === 'decide' ? 'decision' : 'reply', 'decision' => $decision, 'note' => $note, 'text' => $reply, 'by' => (string) ($env['sender']['principal'] ?? ''),
                              'envelope' => $env, 'ts' => gmdate('Y-m-d\TH:i:s\Z')];
            $pdo->prepare("UPDATE estate_tasks SET state = 'queued', result = :res, lease_until = NULL WHERE id = :id")
                ->execute(['res' => json_encode($res, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE), 'id' => $t['id']]);
            if ($t['location_id'] !== null) { node_notify($pdo, (int) $t['location_id']); }
            $task = present_task(task_row($pdo, $t['id']));
        }
    }
    log_activity($pdo, 'estate.inbox.' . $what, 'estate_inbox', $itemId, ['source' => 'desk', 'after' => ['kind' => $item['kind'], 'decision' => $decision, 'task' => $item['task_id'], 'envelope' => $env['id']]]);
    $st = $pdo->prepare('SELECT * FROM estate_inbox WHERE id = :id'); $st->execute(['id' => $itemId]);
    return ['ok' => true, 'item' => present_inbox_item($st->fetch()), 'task' => $task];
}

/** Mark items read. */
function inbox_mark_read(PDO $pdo, array $member, array $ids): int
{
    $ids = array_values(array_filter(array_map('intval', $ids), static fn ($i) => $i > 0));
    if ($ids === []) { return 0; }
    $st = $pdo->prepare("UPDATE estate_inbox SET status = 'read', read_at = now() WHERE member_id = :m AND status = 'unread' AND id = ANY(:ids)");
    $st->execute(['m' => (int) $member['id'], 'ids' => '{' . implode(',', $ids) . '}']);
    return $st->rowCount();
}

// --------------------------------------------------------------------------
// Settings → Estate (an operator): the directory, the last tasks, the actions log
// --------------------------------------------------------------------------

function present_delegation_for_settings(PDO $pdo): array
{
    $agents = estate_agents_answer($pdo)['agents'];
    $st = $pdo->query('SELECT t.*, a.name AS agent_name, a.principal AS agent_principal, l.kind AS node_kind, l.name AS node_name FROM estate_tasks t JOIN estate_agents a ON a.id = t.agent_id
                       LEFT JOIN locations l ON l.id = t.location_id ORDER BY t.created_at DESC LIMIT 30');
    $tasks = array_map(static function (array $t): array {
        $p = present_task($t);
        return ['id' => $p['id'], 'state' => $p['state'], 'ts' => $p['ts'], 'done_ts' => $p['done_ts'], 'agent' => $p['agent']['name'], 'node' => $p['node'], 'node_name' => $t['node_name'] ?? 'coordinator',
                'originator' => $p['originator'], 'sender' => $p['sender'], 'text' => mb_substr($p['input']['text'], 0, 120), 'reason' => $p['reason'],
                'envelope_id' => $p['envelope_id'], 'hop' => $p['hop'], 'models' => is_array($p['provenance']['models'] ?? null) ? count($p['provenance']['models']) : 0,
                'usd' => is_numeric($p['usage']['usd'] ?? null) ? (float) $p['usage']['usd'] : null];
    }, $st->fetchAll());
    $st = $pdo->query('SELECT a.*, l.name AS node_name FROM estate_actions a JOIN locations l ON l.id = a.location_id ORDER BY a.created_at DESC LIMIT 30');
    $actions = array_map('present_action', $st->fetchAll());
    return ['agents' => $agents, 'tasks' => $tasks, 'actions' => $actions, 'coordinator_key' => coordinator_key($pdo)['public_key']];
}

// --------------------------------------------------------------------------
// Authentication for the endpoints both kinds of member call (the directory, the keys, a task record)
// --------------------------------------------------------------------------

/** A node token or a desk token: whichever the bearer is. @return array the context of node_authenticate() or desk_authenticate() */
function estate_authenticate_any(): array
{
    $raw = api_bearer_token();
    if ($raw === '') {
        api_error('unauthorized', 'A valid node or desk token is required.', 401);
    }
    $st = db()->prepare('SELECT scope FROM mcp_access_tokens WHERE token_hash = :h');
    $st->execute(['h' => hash('sha256', $raw)]);
    return $st->fetchColumn() === 'node' ? node_authenticate() : desk_authenticate();
}

/** The JSON-RPC answer of a request against an agent. */
function agent_rpc_answer(PDO $pdo, array $agent, array $ctx): never
{
    $req = json_decode((string) file_get_contents('php://input'), true);
    if (!is_array($req)) {
        api_json(['jsonrpc' => '2.0', 'id' => null, 'error' => ['code' => -32700, 'message' => 'parse error']]);
    }
    $ans = agent_rpc($pdo, $agent, $req, $ctx);
    api_json(['jsonrpc' => '2.0', 'id' => $req['id'] ?? null] + $ans);
}
