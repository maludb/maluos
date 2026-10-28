<?php
declare(strict_types=1);

/**
 * A person's channels to their assistant (db/156; docs/build-specs/assistants-and-messaging.md §6).
 *
 * Every inbound message becomes an ordinary agent message (db/155) from the person to their own
 * assistant — and so an ordinary, ledgered run of it, under its grants, approvals and budget. Only a
 * VERIFIED identity is heard; anything else is dropped and logged, never answered. Replies travel back on
 * the channel the person last used on the thread (agent_messages_delivery_channel(), db/156).
 *
 * Telegram is the Bot API directly (long polling — nothing public); SMS is Twilio (REST out, a signed
 * webhook in); email is the agent's own MaluMail mailbox through MaluMail's mailbox MCP (its signed
 * new-mail webhook in, a poll for unread mail as the safety net, send_message out, threaded). Credentials
 * are tenant secrets, read here and nowhere else; no agent holds one, and the OS holds no mailbox password.
 */
require_once dirname(__DIR__, 2) . '/secrets.php';

const CHANNEL_CODE_MINUTES = 15;
const CHANNEL_THREAD_HOURS = 12;          // a message within this of the last one continues the thread
const CHANNEL_TEXT_MAX = 4000;            // what one inbound message may carry
const TELEGRAM_CHUNK = 3900;              // Telegram's limit is 4096 characters a message
const SMS_CHUNK = 1500;                   // Twilio concatenates up to 1600
const MALUMAIL_MCP_URL = 'https://api.malumail.com/mcp';
const EMAIL_WEBHOOK_SKEW = 300;           // a webhook signed longer ago than this is refused
const EMAIL_POLL_SECONDS = 60;            // the worker's look for unread mail — the webhook's safety net

// ---- transports ---------------------------------------------------------------------------------------

/** One Telegram Bot API call. Answers the decoded `result`, or throws with Telegram's description. */
function telegram_api(string $token, string $method, array $params = [], int $timeout = 30): mixed
{
    $ch = curl_init('https://api.telegram.org/bot' . $token . '/' . $method);
    curl_setopt_array($ch, [
        CURLOPT_POST => true, CURLOPT_POSTFIELDS => json_encode($params, JSON_UNESCAPED_UNICODE),
        CURLOPT_HTTPHEADER => ['Content-Type: application/json'], CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 10, CURLOPT_TIMEOUT => $timeout,
    ]);
    $raw = curl_exec($ch);
    $errno = curl_errno($ch);
    curl_close($ch);
    if ($errno !== 0 || !is_string($raw)) {
        throw new RuntimeException('Telegram did not answer (' . $errno . ').');
    }
    $body = json_decode($raw, true);
    if (!is_array($body) || empty($body['ok'])) {
        throw new RuntimeException('Telegram refused ' . $method . ': ' . (string) ($body['description'] ?? 'no reason'));
    }
    return $body['result'] ?? null;
}

/** Send one SMS through Twilio. Answers the message SID, or throws with Twilio's message. */
function twilio_send_sms(string $accountSid, string $authToken, string $from, string $to, string $text): string
{
    $ch = curl_init('https://api.twilio.com/2010-04-01/Accounts/' . rawurlencode($accountSid) . '/Messages.json');
    curl_setopt_array($ch, [
        CURLOPT_POST => true, CURLOPT_POSTFIELDS => http_build_query(['From' => $from, 'To' => $to, 'Body' => $text]),
        CURLOPT_USERPWD => $accountSid . ':' . $authToken, CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 10, CURLOPT_TIMEOUT => 30,
    ]);
    $raw = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    $body = is_string($raw) ? json_decode($raw, true) : null;
    if ($status < 200 || $status >= 300 || !is_array($body) || empty($body['sid'])) {
        // The exception's code is Twilio's error code (21610: the recipient sent STOP) — K6 reads it.
        throw new RuntimeException('Twilio refused the message: ' . (string) ($body['message'] ?? ('HTTP ' . $status)), (int) ($body['code'] ?? 0));
    }
    return (string) $body['sid'];
}

/**
 * Twilio's webhook signature: base64(HMAC-SHA1(auth token, the full URL + every POST field sorted by
 * name, name followed by value)). Compared in constant time.
 */
function twilio_signature_valid(string $authToken, string $url, array $post, string $signature): bool
{
    ksort($post, SORT_STRING);
    $data = $url;
    foreach ($post as $k => $v) {
        $data .= $k . (is_array($v) ? implode('', $v) : $v);
    }
    return $signature !== '' && hash_equals(base64_encode(hash_hmac('sha1', $data, $authToken, true)), $signature);
}

/**
 * One tool of MaluMail's mailbox MCP (api.malumail.com/mcp; the account's API key must have "Mailbox MCP").
 * Answers the tool's JSON result, or throws with MaluMail's words. No mailbox password is ever involved:
 * MaluMail reaches the mailbox itself (its M3 content tools).
 */
function malumail_mcp(string $apiKey, string $tool, array $args, int $timeout = 30): array
{
    $ch = curl_init(MALUMAIL_MCP_URL);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => json_encode(['jsonrpc' => '2.0', 'id' => 1, 'method' => 'tools/call',
            'params' => ['name' => $tool, 'arguments' => (object) $args]], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
        CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $apiKey, 'Content-Type: application/json',
                               'Accept: application/json, text/event-stream'],
        CURLOPT_RETURNTRANSFER => true, CURLOPT_CONNECTTIMEOUT => 10, CURLOPT_TIMEOUT => $timeout,
    ]);
    $raw = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    $body = is_string($raw) ? json_decode($raw, true) : null;
    if ($status !== 200 || !is_array($body)) {
        throw new RuntimeException('MaluMail did not answer ' . $tool . ' (HTTP ' . $status . ').');
    }
    if (isset($body['error'])) {
        throw new RuntimeException('MaluMail refused ' . $tool . ': ' . (string) ($body['error']['message'] ?? 'no reason'));
    }
    $text = (string) ($body['result']['content'][0]['text'] ?? '');
    if (!empty($body['result']['isError'])) {
        throw new RuntimeException('MaluMail refused ' . $tool . ': ' . mb_substr($text, 0, 300));
    }
    $out = json_decode($text, true);
    return is_array($out) ? $out : [];
}

/**
 * MaluMail's new-mail webhook signature: "t=<unix>,v1=<hex HMAC-SHA256(secret, t . '.' . raw body)>",
 * no older than EMAIL_WEBHOOK_SKEW seconds. Compared in constant time.
 */
function malumail_signature_valid(string $secret, string $header, string $body): bool
{
    if (!preg_match('/^t=(\d+),v1=([0-9a-f]{64})$/', trim($header), $m) || abs(time() - (int) $m[1]) > EMAIL_WEBHOOK_SKEW) {
        return false;
    }
    return hash_equals(hash_hmac('sha256', $m[1] . '.' . $body, $secret), $m[2]);
}

/** The bare address in a From header ("Name <a@b>" → a@b), lower-cased; '' when there is none. */
function email_address_of(string $from): string
{
    $addr = preg_match('/<([^<>\s]+@[^<>\s]+)>/', $from, $m) ? $m[1] : trim($from);
    return filter_var($addr, FILTER_VALIDATE_EMAIL) ? strtolower($addr) : '';
}

/** What the person wrote, without the quoted history a mail client appends to a reply. */
function email_reply_text(string $text): string
{
    $lines = preg_split('/\r\n|\n/', $text) ?: [];
    $out = [];
    foreach ($lines as $line) {
        if ($line === '-- ' || preg_match('/^\s*On .{4,200} wrote:\s*$/', $line) || preg_match('/^-{2,}\s*Original Message\s*-{2,}/i', $line)
            || preg_match('/^_{10,}$/', $line) || preg_match('/^From: .+/', $line) && $out !== []) {
            break;                                                      // the quoted part starts here
        }
        if (!str_starts_with(ltrim($line), '>')) {
            $out[] = $line;
        }
    }
    return trim(implode("\n", $out));
}

/** Split text for a channel that caps a message's length, on paragraph and line breaks where it can. */
function channel_chunks(string $text, int $max): array
{
    $text = trim($text);
    $out = [];
    while (mb_strlen($text) > $max) {
        $cut = mb_strrpos(mb_substr($text, 0, $max), "\n");
        $cut = $cut === false || $cut < $max / 2 ? $max : $cut;
        $out[] = rtrim(mb_substr($text, 0, $cut));
        $text = ltrim(mb_substr($text, $cut));
    }
    if ($text !== '') {
        $out[] = $text;
    }
    return $out;
}

// ---- endpoints and identities -------------------------------------------------------------------------

/** The agent's live endpoint on a channel, with its credential decrypted, or null. */
function channel_endpoint(PDO $pdo, string $channel, ?int $agentId = null, ?string $address = null): ?array
{
    $st = $pdo->prepare('SELECT * FROM agent_channel_endpoints WHERE channel = :c AND active
                            AND (CAST(:a AS bigint) IS NULL OR agent_member_id = CAST(:a AS bigint))
                            AND (CAST(:addr AS text) IS NULL OR address = CAST(:addr AS text))
                          ORDER BY id LIMIT 1');
    $st->execute(['c' => $channel, 'a' => $agentId, 'addr' => $address]);
    $row = $st->fetch();
    if ($row === false) {
        return null;
    }
    $row['config'] = json_decode((string) $row['config'], true) ?: [];
    $row['secret'] = $row['secret_id'] !== null ? read_tenant_secret($pdo, (int) $row['secret_id']) : null;
    return $row;
}

/**
 * Start linking a channel to a person: a one-time six-digit code, kept only as a hash, good for 15 minutes.
 * Telegram: the person sends the code to the bot. SMS/email: the code is sent to the address given, and the
 * person enters it (channel_link_confirm()). Answers the code.
 */
function channel_link_start(PDO $pdo, int $memberId, string $channel, ?string $address = null, int $minutes = CHANNEL_CODE_MINUTES): string
{
    $minutes = max(5, min($minutes, 24 * 60));
    $code = (string) random_int(100000, 999999);
    $pdo->prepare("UPDATE member_channel_identities SET removed_at = now()
                    WHERE member_id = :m AND channel = :c AND verified_at IS NULL AND removed_at IS NULL")
        ->execute(['m' => $memberId, 'c' => $channel]);
    $pdo->prepare('INSERT INTO member_channel_identities (member_id, channel, address, label, verify_code_hash, code_expires_at)
                   VALUES (:m, :c, :a, :a, :h, now() + make_interval(mins => :mins))')
        ->execute(['m' => $memberId, 'c' => $channel, 'a' => $address, 'h' => hash('sha256', $channel . ':' . $code), 'mins' => $minutes]);
    return $code;
}

/** The pending link a code opens on this channel, or null. */
function channel_link_by_code(PDO $pdo, string $channel, string $code): ?array
{
    $st = $pdo->prepare('SELECT * FROM member_channel_identities
                          WHERE channel = :c AND verify_code_hash = :h AND verified_at IS NULL AND removed_at IS NULL
                            AND code_expires_at > now() LIMIT 1');
    $st->execute(['c' => $channel, 'h' => hash('sha256', $channel . ':' . $code)]);
    return $st->fetch() ?: null;
}

/** Verify a pending link: the address (and where to write back) become the person's on this channel. */
function channel_link_verify(PDO $pdo, array $pending, string $address, ?string $chatRef, ?string $label): void
{
    $pdo->prepare('UPDATE member_channel_identities SET removed_at = now()
                    WHERE channel = :c AND address = :a AND verified_at IS NOT NULL AND removed_at IS NULL')
        ->execute(['c' => $pending['channel'], 'a' => $address]);          // an address belongs to one person
    $st = $pdo->prepare('SELECT count(*) FROM member_channel_identities WHERE member_id = :m AND preferred AND removed_at IS NULL');
    $st->execute(['m' => (int) $pending['member_id']]);
    $first = (int) $st->fetchColumn() === 0;
    $pdo->prepare('UPDATE member_channel_identities SET address = :a, chat_ref = :ch, label = :l, verified_at = now(),
                          verify_code_hash = NULL, code_expires_at = NULL, preferred = :p WHERE id = :id')
        ->execute(['a' => $address, 'ch' => $chatRef, 'l' => $label ?? $address, 'p' => $first ? 't' : 'f', 'id' => (int) $pending['id']]);
    log_activity($pdo, 'channel_identity.verify', 'member', (int) $pending['member_id'], [
        'actor_member_id' => (int) $pending['member_id'], 'source' => 'web',
        'after' => ['channel' => $pending['channel'], 'label' => $label ?? $address, 'preferred' => $first]]);
}

/** The person a verified address on a channel belongs to, or null. */
function channel_identity(PDO $pdo, string $channel, string $address): ?array
{
    $st = $pdo->prepare("SELECT i.*, m.display_name FROM member_channel_identities i JOIN members m ON m.id = i.member_id
                          WHERE i.channel = :c AND i.address = :a AND i.verified_at IS NOT NULL AND i.removed_at IS NULL
                            AND m.status = 'active' LIMIT 1");
    $st->execute(['c' => $channel, 'a' => $address]);
    return $st->fetch() ?: null;
}

// ---- inbound ------------------------------------------------------------------------------------------

/**
 * One inbound message on an agent's endpoint. A six-digit code from an unlinked sender completes a link;
 * a message from the verified person the agent serves becomes a message to the agent; anything else is
 * dropped and logged. Answers [what happened, a reply to send back on the channel or null].
 */
function channel_inbound(PDO $pdo, array $endpoint, string $sender, ?string $chatRef, ?string $senderLabel,
                         string $text, ?string $externalRef, ?string $subject = null): array
{
    $channel = (string) $endpoint['channel'];
    $text = trim(mb_substr($text, 0, CHANNEL_TEXT_MAX));
    $who = channel_identity($pdo, $channel, $sender);
    if ($who === null) {
        if (preg_match('/^(?:\/start\s+)?(\d{6})$/', $text, $m) && ($pending = channel_link_by_code($pdo, $channel, $m[1])) !== null) {
            channel_link_verify($pdo, $pending, $sender, $chatRef, $senderLabel);
            $name = (string) $pdo->query('SELECT display_name FROM members WHERE id = ' . (int) $pending['member_id'])->fetchColumn();
            return ['linked', 'Linked. This ' . $channel . ' account now reaches your assistant, ' . $name . '.'];
        }
        log_activity($pdo, 'channel.inbound_dropped', 'member', (int) $endpoint['agent_member_id'], [
            'actor_member_id' => null, 'source' => 'cron',
            'after' => ['channel' => $channel, 'sender' => mb_substr(hash('sha256', $sender), 0, 12), 'why' => 'unlinked sender']]);
        return ['dropped', null];                                       // never answered: an unknown sender learns nothing
    }
    $st = $pdo->prepare('SELECT principal_member_id FROM agent_profiles WHERE member_id = :a');
    $st->execute(['a' => (int) $endpoint['agent_member_id']]);
    if ((int) $st->fetchColumn() !== (int) $who['member_id']) {
        log_activity($pdo, 'channel.inbound_dropped', 'member', (int) $endpoint['agent_member_id'], [
            'actor_member_id' => (int) $who['member_id'], 'source' => 'cron',
            'after' => ['channel' => $channel, 'why' => 'not this assistant\'s person']]);
        return ['dropped', null];
    }
    if ($text === '') {
        return ['empty', null];
    }
    // Continue the latest thread between the person and the assistant if it is recent, else open one.
    $st = $pdo->prepare("SELECT m.thread_id FROM agent_messages m JOIN agent_message_threads t ON t.id = m.thread_id
                          WHERE ((m.from_member_id = :p AND m.to_member_id = :a) OR (m.from_member_id = :a AND m.to_member_id = :p))
                            AND t.closed_at IS NULL AND m.created_at > now() - make_interval(hours => :h)
                          ORDER BY m.created_at DESC LIMIT 1");
    $st->execute(['p' => (int) $who['member_id'], 'a' => (int) $endpoint['agent_member_id'], 'h' => CHANNEL_THREAD_HOURS]);
    $thread = $st->fetchColumn() ?: null;
    $subject = trim((string) $subject) !== '' ? mb_substr(trim((string) $subject), 0, 300)       // an email's own subject
        : mb_substr(preg_replace('/\s+/', ' ', $text) ?? '', 0, 80);
    try {
        $st = $pdo->prepare("SELECT app_message_send(:f, :t, 'request', :s, :b, :th, 'normal', :c, NULL, :ref, NULL)");
        $st->execute(['f' => (int) $who['member_id'], 't' => (int) $endpoint['agent_member_id'], 's' => $subject, 'b' => $text,
                      'th' => $thread, 'c' => $channel, 'ref' => $externalRef]);
        $messageId = (int) $st->fetchColumn();
    } catch (PDOException $ex) {
        if ($ex->getCode() === '23505') {
            return ['duplicate', null];                                  // the same message delivered twice
        }
        throw $ex;
    }
    log_activity($pdo, 'agent_message.send', 'agent_message', $messageId, [
        'actor_member_id' => (int) $who['member_id'], 'source' => 'web',
        'after' => ['to_member_id' => (int) $endpoint['agent_member_id'], 'channel' => $channel, 'kind' => 'request']]);
    return ['delivered', null];
}

/**
 * One message in an agent's mailbox, named by uid (from the new-mail webhook or the poll). Handled at most
 * once: under a per-endpoint lock, a message already marked read is skipped, and reading marks it. Then it
 * is an ordinary inbound message from its From address; a reply (a link confirmation) goes back threaded.
 * Answers what happened.
 */
function email_inbound(PDO $pdo, array $endpoint, int $uid): string
{
    $pdo->beginTransaction();
    try {
        $pdo->prepare('SELECT pg_advisory_xact_lock(hashtext(:k))')->execute(['k' => 'email-inbound:' . $endpoint['id']]);
        $msg = malumail_mcp((string) $endpoint['secret'], 'read_message',
            ['address' => $endpoint['address'], 'uid' => $uid, 'mark_seen' => true]);
        if (in_array('\\Seen', $msg['flags'] ?? [], true)) {
            $pdo->commit();
            return 'already read';
        }
        $h = $msg['headers'] ?? [];
        $from = email_address_of((string) ($h['from'] ?? ''));
        if ($from === '' || $from === strtolower((string) $endpoint['address'])) {
            $pdo->commit();
            return 'ignored (no sender, or its own)';
        }
        $text = email_reply_text((string) ($msg['text'] ?? ''));
        if (!empty($msg['attachments'])) {
            $text .= "\n\n(" . count($msg['attachments']) . ' attachment(s) not read — only text is read.)';
        }
        $messageId = trim((string) ($h['message_id'] ?? ''));
        $subject = trim(preg_replace('/^\s*((re|fwd?|aw):\s*)+/i', '', (string) ($h['subject'] ?? '')) ?? '');
        [$what, $reply] = channel_inbound($pdo, $endpoint, $from, $messageId !== '' ? $messageId : null,
            (string) ($h['from'] ?? $from), $text !== '' ? $text : '(an email with no text)',
            $messageId !== '' ? $messageId : 'mm:' . $endpoint['address'] . ':' . $uid, $subject !== '' ? $subject : null);
        $pdo->commit();
    } catch (Throwable $e) {
        if ($pdo->inTransaction()) {
            $pdo->rollBack();
        }
        if (isset($msg) && !in_array('\\Seen', $msg['flags'] ?? [], true)) {
            try {                                                       // unread again, so the poll tries it once more
                malumail_mcp((string) $endpoint['secret'], 'mark_message', ['address' => $endpoint['address'], 'uid' => $uid, 'seen' => false]);
            } catch (Throwable) {
            }
        }
        throw $e;
    }
    if ($reply !== null) {
        malumail_mcp((string) $endpoint['secret'], 'send_message', array_filter([
            'address' => $endpoint['address'], 'to' => [$from], 'subject' => 'Re: ' . ($subject !== '' ? $subject : 'your message'),
            'text' => $reply, 'in_reply_to' => $messageId !== '' ? $messageId : null,
        ], static fn ($v) => $v !== null));
    }
    return $what;
}

/** The safety net for the webhook: every unread message in an agent's inbox, oldest first. Answers log lines. */
function email_poll(PDO $pdo, array $endpoint): array
{
    $list = malumail_mcp((string) $endpoint['secret'], 'list_messages',
        ['address' => $endpoint['address'], 'unread_only' => true, 'limit' => 20]);
    $notes = [];
    foreach (array_reverse($list['messages'] ?? []) as $m) {
        try {
            $notes[] = 'email ' . $endpoint['address'] . ': uid ' . $m['uid'] . ' ' . email_inbound($pdo, $endpoint, (int) $m['uid']);
        } catch (Throwable $e) {
            $notes[] = 'email ' . $endpoint['address'] . ': uid ' . $m['uid'] . ' failed — ' . $e->getMessage();
        }
    }
    return $notes;
}

/** Subject and threading headers for an email on a thread: a reply to the latest email the person sent on it. */
function email_thread_headers(PDO $pdo, int $threadId, string $fallbackSubject): array
{
    $st = $pdo->prepare("SELECT subject, external_ref FROM agent_messages
                          WHERE thread_id = :t AND channel = 'email' AND external_ref LIKE '<%>'
                          ORDER BY created_at DESC LIMIT 20");
    $st->execute(['t' => $threadId]);
    $rows = $st->fetchAll();
    if ($rows === []) {
        return [$fallbackSubject, null, []];
    }
    return ['Re: ' . $rows[0]['subject'], (string) $rows[0]['external_ref'], array_reverse(array_column($rows, 'external_ref'))];
}

// ---- outbound -----------------------------------------------------------------------------------------

/**
 * Send what agents wrote to people on Telegram, SMS or email (a reply on the thread's email). Each message goes from
 * the sending agent's endpoint on that channel to the person's verified identity there. Up to five tries.
 * Answers one line per message, for the worker's log.
 */
function channel_deliver_pending(PDO $pdo, int $limit = 20): array
{
    $st = $pdo->prepare("SELECT m.* FROM agent_messages m
                          WHERE m.delivered_at IS NULL AND m.delivery_channel IN ('telegram', 'sms', 'email') AND m.delivery_attempts < 5
                          ORDER BY m.created_at LIMIT :n");
    $st->bindValue('n', $limit, PDO::PARAM_INT);
    $st->execute();
    $notes = [];
    foreach ($st->fetchAll() as $m) {
        $channel = (string) $m['delivery_channel'];
        $error = null;
        try {
            $endpoint = channel_endpoint($pdo, $channel, (int) $m['from_member_id']);
            $who = $pdo->prepare('SELECT * FROM member_channel_identities WHERE member_id = :p AND channel = :c
                                     AND verified_at IS NOT NULL AND removed_at IS NULL ORDER BY verified_at DESC LIMIT 1');
            $who->execute(['p' => (int) $m['to_member_id'], 'c' => $channel]);
            $identity = $who->fetch();
            if ($endpoint === null || $endpoint['secret'] === null) {
                throw new RuntimeException('the sending agent has no ' . $channel . ' endpoint');
            }
            if ($identity === false) {
                throw new RuntimeException('the person has no verified ' . $channel . ' identity');
            }
            $text = (string) $m['body'];
            if ($channel === 'telegram') {
                foreach (channel_chunks($text, TELEGRAM_CHUNK) as $part) {
                    telegram_api((string) $endpoint['secret'], 'sendMessage', ['chat_id' => $identity['chat_ref'] ?: $identity['address'], 'text' => $part]);
                }
            } elseif ($channel === 'email') {
                [$subject, $inReplyTo, $refs] = email_thread_headers($pdo, (int) $m['thread_id'], (string) $m['subject']);
                $name = $pdo->prepare('SELECT display_name FROM members WHERE id = :id');
                $name->execute(['id' => (int) $m['from_member_id']]);
                malumail_mcp((string) $endpoint['secret'], 'send_message', array_filter([
                    'address' => $endpoint['address'], 'to' => [(string) $identity['address']], 'subject' => mb_substr($subject, 0, 300),
                    'text' => $text, 'from_name' => str_replace('"', '', (string) $name->fetchColumn()),
                    'in_reply_to' => $inReplyTo, 'references' => $refs ?: null,
                ], static fn ($v) => $v !== null && $v !== ''));
            } else {
                foreach (channel_chunks($text, SMS_CHUNK) as $part) {
                    twilio_send_sms((string) ($endpoint['config']['account_sid'] ?? ''), (string) $endpoint['secret'],
                        (string) $endpoint['address'], (string) $identity['address'], $part);
                }
            }
        } catch (Throwable $e) {
            $error = mb_substr($e->getMessage(), 0, 500);
        }
        $pdo->prepare('UPDATE agent_messages SET delivery_attempts = delivery_attempts + 1, delivery_error = :e,
                              delivered_at = CASE WHEN CAST(:e AS text) IS NULL THEN now() ELSE NULL END WHERE id = :id')
            ->execute(['e' => $error, 'id' => (int) $m['id']]);
        $notes[] = 'message ' . $m['id'] . ' on ' . $channel . ': ' . ($error ?? 'delivered');
    }
    return $notes;
}
