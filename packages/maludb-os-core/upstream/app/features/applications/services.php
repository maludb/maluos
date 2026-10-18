<?php
declare(strict_types=1);

/**
 * Kernel services for applications (db/161; docs/build-specs/kernel-app-services.md):
 *   K6 — an application texts a member through the kernel (the business's notification number; the application
 *        never sees the number or a Twilio key);
 *   K7 — an application reads another's shared tool through the kernel, over a connection a super-admin approved.
 */

require_once dirname(__DIR__, 2) . '/secrets.php';
require_once dirname(__DIR__) . '/channels/channels.php';
require_once __DIR__ . '/roles.php';

const NOTIFY_TEXT_MAX = 480;              // the application's words; its name is put in front
const NOTIFY_MEMBER_DAY = 30;             // texts a member a day, per application
const NOTIFY_APP_DAY = 2000;              // texts a day, per application
const NOTIFY_ATTEMPTS = 5;
const APP_READ_MAX_BYTES = 262144;        // an answer passed back is capped at 256 kB

// ---- K6 ----------------------------------------------------------------------------------------------------------

/** The business's live SMS notification number with its credential, or null. */
function notify_endpoint(PDO $pdo): ?array
{
    $row = $pdo->query("SELECT * FROM notification_endpoints WHERE channel = 'sms' AND active ORDER BY id LIMIT 1")->fetch();
    if ($row === false) {
        return null;
    }
    $row['config'] = is_string($row['config']) ? (json_decode($row['config'], true) ?: []) : (array) $row['config'];
    $row['secret'] = $row['secret_id'] !== null ? read_tenant_secret($pdo, (int) $row['secret_id']) : null;
    return $row['secret'] === null || empty($row['config']['account_sid']) ? null : $row;
}

/**
 * Queue one text from an application to a member. Answers [HTTP status, payload]: 202 with the notification, or a
 * refusal whose code the application can act on (no_sender, not_held, no_verified_phone, opted_out, rate_limited,
 * invalid). The checks, in order: the sender exists, the text fits, the member holds the application, has a
 * verified phone, has not opted out, and the limits.
 */
function notify_sms_queue(PDO $pdo, array $app, int $memberId, string $text, ?string $reference): array
{
    $text = trim(preg_replace('/\s+/u', ' ', $text));
    if ($text === '' || mb_strlen($text) > NOTIFY_TEXT_MAX) {
        return [422, ['code' => 'invalid', 'message' => 'The text must be 1 to ' . NOTIFY_TEXT_MAX . ' characters.']];
    }
    if ($reference !== null && ($reference === '' || mb_strlen($reference) > 120)) {
        return [422, ['code' => 'invalid', 'message' => 'reference is at most 120 characters.']];
    }
    if (notify_endpoint($pdo) === null) {
        return [503, ['code' => 'no_sender', 'message' => 'The business has no notification number yet — send it by email.']];
    }
    $st = $pdo->prepare("SELECT m.id,
                                (m.status = 'active' AND (m.business_role = 'super_admin'
                                     OR EXISTS (SELECT 1 FROM app_member_grants(:a, m.id)))) AS holds,
                                EXISTS (SELECT 1 FROM member_channel_identities i WHERE i.member_id = m.id AND i.channel = 'sms'
                                          AND i.verified_at IS NOT NULL AND i.removed_at IS NULL) AS has_phone,
                                EXISTS (SELECT 1 FROM member_notification_optouts o WHERE o.member_id = m.id AND o.channel = 'sms'
                                          AND (o.application_id IS NULL OR o.application_id = :a)) AS opted_out
                           FROM members m WHERE m.id = :m AND m.member_kind = 'human'");
    $st->execute(['a' => (int) $app['id'], 'm' => $memberId]);
    $who = $st->fetch();
    if ($who === false || !$who['holds']) {
        return [422, ['code' => 'not_held', 'message' => 'That member does not hold this application.']];
    }
    if (!$who['has_phone']) {
        return [422, ['code' => 'no_verified_phone', 'message' => 'That member has no verified phone number in the operating system.']];
    }
    if ($who['opted_out']) {
        return [422, ['code' => 'opted_out', 'message' => 'That member has turned these texts off.']];
    }
    $count = $pdo->prepare("SELECT count(*) FILTER (WHERE member_id = :m), count(*) FROM application_notifications
                             WHERE application_id = :a AND created_at > now() - interval '1 day'");
    $count->execute(['a' => (int) $app['id'], 'm' => $memberId]);
    [$toMember, $total] = array_map('intval', $count->fetch(PDO::FETCH_NUM));
    if ($toMember >= NOTIFY_MEMBER_DAY || $total >= NOTIFY_APP_DAY) {
        return [422, ['code' => 'rate_limited', 'message' => 'Too many texts in the last day — send it by email.']];
    }
    $ins = $pdo->prepare('INSERT INTO application_notifications (application_id, member_id, body, reference)
                          VALUES (:a, :m, :b, :r) RETURNING id, created_at');
    $ins->execute(['a' => (int) $app['id'], 'm' => $memberId, 'b' => $app['name'] . ': ' . $text, 'r' => $reference]);
    $row = $ins->fetch();
    log_activity($pdo, 'application.notify', 'application', (int) $app['id'],
        ['source' => 'application', 'after' => ['notification_id' => (int) $row['id'], 'member_id' => $memberId, 'channel' => 'sms', 'reference' => $reference]]);
    return [202, ['notification' => ['id' => (int) $row['id'], 'status' => 'queued', 'created_at' => (string) $row['created_at']]]];
}

/** One queued text's state, for the application that sent it. */
function notify_status(PDO $pdo, array $app, int $id): ?array
{
    $st = $pdo->prepare('SELECT id, created_at, sent_at, failed_at, error, attempts FROM application_notifications WHERE id = :id AND application_id = :a');
    $st->execute(['id' => $id, 'a' => (int) $app['id']]);
    $n = $st->fetch();
    if ($n === false) {
        return null;
    }
    return ['id' => (int) $n['id'], 'status' => $n['sent_at'] !== null ? 'sent' : ($n['failed_at'] !== null ? 'failed' : 'queued'),
            'created_at' => (string) $n['created_at'], 'sent_at' => $n['sent_at'], 'error' => $n['error'], 'attempts' => (int) $n['attempts']];
}

/**
 * The channels worker's pass over application texts: send what is queued from the notification number, to the
 * member's verified phone as it is now. Twilio's 21610 (the recipient sent STOP) opts the member out of every
 * application's texts and fails the text at once; anything else is retried up to NOTIFY_ATTEMPTS times.
 */
function notify_deliver_pending(PDO $pdo, int $limit = 20): array
{
    $endpoint = null;
    $notes = [];
    $st = $pdo->prepare('SELECT * FROM application_notifications WHERE sent_at IS NULL AND failed_at IS NULL ORDER BY created_at LIMIT :n');
    $st->bindValue('n', $limit, PDO::PARAM_INT);
    $st->execute();
    foreach ($st->fetchAll() as $n) {
        $error = null;
        $final = false;
        try {
            $endpoint ??= notify_endpoint($pdo);
            if ($endpoint === null) {
                throw new RuntimeException('the business has no notification number');
            }
            $who = $pdo->prepare("SELECT i.address FROM member_channel_identities i
                                   WHERE i.member_id = :m AND i.channel = 'sms' AND i.verified_at IS NOT NULL AND i.removed_at IS NULL
                                     AND NOT EXISTS (SELECT 1 FROM member_notification_optouts o WHERE o.member_id = i.member_id AND o.channel = 'sms'
                                                       AND (o.application_id IS NULL OR o.application_id = :a))
                                   ORDER BY i.verified_at DESC LIMIT 1");
            $who->execute(['m' => (int) $n['member_id'], 'a' => (int) $n['application_id']]);
            $to = $who->fetchColumn();
            if ($to === false) {
                $final = true;
                throw new RuntimeException('the member has no verified phone, or turned these texts off');
            }
            twilio_send_sms((string) $endpoint['config']['account_sid'], (string) $endpoint['secret'], (string) $endpoint['address'], (string) $to, (string) $n['body']);
        } catch (Throwable $e) {
            $error = mb_substr($e->getMessage(), 0, 500);
            if ($e->getCode() === 21610) {
                $final = true;
                $pdo->prepare("INSERT INTO member_notification_optouts (member_id, application_id, channel, reason)
                               VALUES (:m, NULL, 'sms', 'carrier_stop') ON CONFLICT DO NOTHING")->execute(['m' => (int) $n['member_id']]);
            }
        }
        $attempts = (int) $n['attempts'] + 1;
        $failed = $error !== null && ($final || $attempts >= NOTIFY_ATTEMPTS);
        $pdo->prepare('UPDATE application_notifications SET attempts = :t, error = :e,
                              sent_at = CASE WHEN CAST(:e AS text) IS NULL THEN now() END,
                              failed_at = CASE WHEN CAST(:f AS boolean) THEN now() END WHERE id = :id')
            ->execute(['t' => $attempts, 'e' => $error, 'f' => $failed ? 't' : 'f', 'id' => (int) $n['id']]);
        $notes[] = 'application text ' . $n['id'] . ': ' . ($error === null ? 'sent' : ($failed ? 'failed' : 'will retry') . ' — ' . $error);
    }
    return $notes;
}

// ---- K7 ----------------------------------------------------------------------------------------------------------

/**
 * The installer's step: record what an application shares (its maludb-os.json shares[]; a share it no longer
 * lists is withdrawn, never deleted) and propose the connections its reads[] ask for. Answers what changed.
 */
function application_services_sync(PDO $pdo, int $appId, array $shares, array $reads): array
{
    $out = ['shares' => 0, 'withdrawn' => 0, 'proposed' => 0, 'waiting' => []];
    $keep = [];
    foreach ($shares as $s) {
        $tool = strtolower((string) ($s['tool'] ?? ''));
        if (!preg_match('/^[a-z][a-z0-9_]{0,63}$/', $tool)) {
            continue;
        }
        $keep[] = $tool;
        $timeout = (int) ($s['timeout_seconds'] ?? 8);                                      // K26 (db/173): 1–60, default 8
        $pdo->prepare('INSERT INTO application_shares (application_id, tool, description, scoped, people, timeout_seconds) VALUES (:a, :t, :d, :s, :p, :o)
                       ON CONFLICT (application_id, tool) DO UPDATE SET description = EXCLUDED.description, scoped = EXCLUDED.scoped,
                                                                       people = EXCLUDED.people, timeout_seconds = EXCLUDED.timeout_seconds,
                                                                       withdrawn_at = NULL, updated_at = now()')
            ->execute(['a' => $appId, 't' => $tool, 'd' => (string) ($s['description'] ?? ''), 's' => !empty($s['scoped']) ? 't' : 'f',
                       'p' => !empty($s['people']) ? 't' : 'f', 'o' => max(1, min(60, $timeout > 0 ? $timeout : 8))]);
        $out['shares']++;
    }
    $w = $pdo->prepare('UPDATE application_shares SET withdrawn_at = now(), updated_at = now()
                         WHERE application_id = :a AND withdrawn_at IS NULL AND NOT (tool = ANY (CAST(:k AS text[])))');
    $w->execute(['a' => $appId, 'k' => '{' . implode(',', $keep) . '}']);
    $out['withdrawn'] = $w->rowCount();
    foreach ($reads as $r) {
        $provider = $pdo->prepare("SELECT id FROM applications WHERE app_key = :k AND status <> 'retired'");
        $provider->execute(['k' => (string) ($r['app'] ?? '')]);
        $pid = $provider->fetchColumn();
        $tool = strtolower((string) ($r['tool'] ?? ''));
        if ($pid === false || $tool === '') {
            $out['waiting'][] = ($r['app'] ?? '?') . '.' . $tool . ' (the provider is not installed yet)';
            continue;
        }
        $ins = $pdo->prepare('INSERT INTO application_connections (consumer_id, provider_id, tool, why) VALUES (:c, :p, :t, :w)
                              ON CONFLICT (consumer_id, provider_id, tool) WHERE revoked_at IS NULL DO NOTHING');
        $ins->execute(['c' => $appId, 'p' => (int) $pid, 't' => $tool, 'w' => (string) ($r['why'] ?? '')]);
        $out['proposed'] += $ins->rowCount();
    }
    return $out;
}

/** A super-admin approves or revokes a connection. Answers the connection, or throws with the reason. */
function application_connection_decide(PDO $pdo, int $connectionId, string $decision, int $by): array
{
    $st = $pdo->prepare('SELECT * FROM application_connections WHERE id = :id');
    $st->execute(['id' => $connectionId]);
    $c = $st->fetch();
    if ($c === false || $c['revoked_at'] !== null) {
        throw new RuntimeException('No such live connection.');
    }
    if ($decision === 'approve') {
        if ($c['approved_at'] !== null) {
            return $c;
        }
        $people = $pdo->prepare('SELECT s.people, a.directory_writes FROM application_shares s, applications a
                                  WHERE s.application_id = :p AND s.tool = :t AND a.id = :c');
        $people->execute(['p' => (int) $c['provider_id'], 't' => $c['tool'], 'c' => (int) $c['consumer_id']]);
        $row = $people->fetch();
        if ($row !== false && $row['people'] && !$row['directory_writes']) {
            throw new RuntimeException('That tool answers about people: only an application registered for directory writes (HR) may be connected to it.');
        }
        $pdo->prepare('UPDATE application_connections SET approved_by = :b, approved_at = now() WHERE id = :id')->execute(['b' => $by, 'id' => $connectionId]);
    } elseif ($decision === 'revoke') {
        $pdo->prepare('UPDATE application_connections SET revoked_by = :b, revoked_at = now() WHERE id = :id')->execute(['b' => $by, 'id' => $connectionId]);
    } else {
        throw new RuntimeException('approve or revoke');
    }
    log_activity($pdo, 'application_connection.' . $decision, 'application', (int) $c['consumer_id'],
        ['actor_member_id' => $by, 'after' => ['connection_id' => $connectionId, 'provider_id' => (int) $c['provider_id'], 'tool' => $c['tool']]]);
    $st->execute(['id' => $connectionId]);
    return $st->fetch();
}

/** K26: the arguments a consumer may not set — the kernel alone says who is asking (the headers), and `scope_id` is the kernel's. */
const APP_READ_RESERVED_ARGUMENTS = ['scope_id', 'consumer', 'consumer_agent_id', 'as_agent'];

/**
 * K7: the consumer asks for the provider's shared tool. Answers [HTTP status, payload]. The checks, in order: the
 * provider exists and shares the tool; an approved, unrevoked connection; for a scoped share, a location both serve
 * (the provider is handed its own scope id for it); then the call as the kernel, the answer passed back unchanged.
 * K26 (2026-10-06): the call carries the consumer's identity in two headers — X-OS-Consumer (its app key) and
 * X-OS-Consumer-Agent (its expert agent's member id, when it has one) — after removing any identity the consumer put in
 * the arguments; it waits the share's own timeout_seconds (db/173) for the answer.
 */
function application_read(PDO $pdo, array $consumer, string $providerKey, string $tool, array $arguments, ?int $locationId): array
{
    $started = microtime(true);
    $refuse = static function (int $status, string $code, string $message) use ($pdo, $consumer, $providerKey, $tool, $locationId, $started): array {
        log_activity($pdo, 'application.read', 'application', (int) $consumer['id'], ['source' => 'application',
            'after' => ['provider' => $providerKey, 'tool' => $tool, 'location_id' => $locationId, 'outcome' => $code,
                        'ms' => (int) round((microtime(true) - $started) * 1000)]]);
        return [$status, ['code' => $code, 'message' => $message]];
    };
    $st = $pdo->prepare("SELECT a.id, a.app_key, a.status, s.scoped, s.people, s.withdrawn_at, s.timeout_seconds
                           FROM applications a LEFT JOIN application_shares s ON s.application_id = a.id AND s.tool = :t
                          WHERE a.app_key = :k AND a.status <> 'retired'");
    $st->execute(['k' => $providerKey, 't' => $tool]);
    $p = $st->fetch();
    if ($p === false || $p['scoped'] === null || $p['withdrawn_at'] !== null) {
        return $refuse(403, 'not_shared', 'That application does not share that tool.');
    }
    if ($p['people'] && empty($consumer['directory_writes'])) {
        // Checked before the connection: even an approved one (made before the tool was marked) does not open it.
        return $refuse(403, 'people_restricted', 'That tool answers about people: only an application registered for directory writes (HR) may read it.');
    }
    $c = $pdo->prepare('SELECT 1 FROM application_connections WHERE consumer_id = :c AND provider_id = :p AND tool = :t
                         AND approved_at IS NOT NULL AND revoked_at IS NULL');
    $c->execute(['c' => (int) $consumer['id'], 'p' => (int) $p['id'], 't' => $tool]);
    if ($c->fetchColumn() === false) {
        return $refuse(403, 'no_connection', 'No approved connection to that tool — a super-admin approves it in the operating system.');
    }
    foreach (APP_READ_RESERVED_ARGUMENTS as $reserved) {
        unset($arguments[$reserved]);
    }
    // K26: who is asking, from the consumer's own row — never from what it sent.
    $who = $pdo->prepare('SELECT app_key, sme_agent_member_id FROM applications WHERE id = :id');
    $who->execute(['id' => (int) $consumer['id']]);
    $me = $who->fetch() ?: ['app_key' => (string) ($consumer['app_key'] ?? ''), 'sme_agent_member_id' => null];
    $headers = ['X-OS-Consumer: ' . $me['app_key']];
    if ($me['sme_agent_member_id'] !== null) {
        $headers[] = 'X-OS-Consumer-Agent: ' . (int) $me['sme_agent_member_id'];
    }
    $timeout = (int) ($p['timeout_seconds'] ?? 8);
    if ($p['scoped']) {
        if ($locationId === null) {
            return $refuse(422, 'invalid', 'This tool is per site: name the location_id.');
        }
        $sc = $pdo->prepare('SELECT application_id, id FROM application_scopes
                              WHERE location_id = :l AND removed_at IS NULL AND application_id IN (:c, :p)');
        $sc->execute(['l' => $locationId, 'c' => (int) $consumer['id'], 'p' => (int) $p['id']]);
        $scopes = [];
        foreach ($sc->fetchAll() as $row) {
            $scopes[(int) $row['application_id']] = (int) $row['id'];
        }
        if (!isset($scopes[(int) $consumer['id']], $scopes[(int) $p['id']])) {
            return $refuse(403, 'not_at_location', 'Both applications must serve that site.');
        }
        $arguments['scope_id'] = $scopes[(int) $p['id']];
    }
    $eps = $pdo->prepare("SELECT url FROM application_endpoints WHERE application_id = :a AND kind = 'mcp' AND status = 'active' ORDER BY id");
    $eps->execute(['a' => (int) $p['id']]);
    $why = [];
    foreach ($eps->fetchAll(PDO::FETCH_COLUMN) as $url) {
        try {
            $result = mcp_call_tool_as_kernel((string) $url, (string) $p['app_key'], $tool, $arguments, $timeout, $headers);
            if (strlen((string) json_encode($result)) > APP_READ_MAX_BYTES) {
                return $refuse(502, 'provider_failed', 'The answer is larger than 256 kB — ask for a shorter period.');
            }
            log_activity($pdo, 'application.read', 'application', (int) $consumer['id'], ['source' => 'application',
                'after' => ['provider' => $providerKey, 'tool' => $tool, 'location_id' => $locationId, 'outcome' => 'ok',
                            'consumer_agent_id' => $me['sme_agent_member_id'] === null ? null : (int) $me['sme_agent_member_id'], 'timeout_seconds' => $timeout,
                            'ms' => (int) round((microtime(true) - $started) * 1000)]]);
            return [200, ['result' => $result, 'provider' => $providerKey, 'tool' => $tool]];
        } catch (RuntimeException $e) {
            $why[] = $e->getMessage();
        }
    }
    return $refuse(502, 'provider_failed', $why === [] ? 'The provider has no MCP endpoint.' : implode(' ', $why));
}
