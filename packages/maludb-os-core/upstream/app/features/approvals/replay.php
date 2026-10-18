<?php
declare(strict_types=1);

/**
 * Replaying an approved action (docs/build-specs/approvals-execution.md, "The replay").
 *
 * The paused request was stored whole: handler_path + request_body. On approval it is POSTed again
 * to the SAME handler on localhost AS THE REQUESTER, so every gate, validation and log line in
 * that handler runs as it would have. check_approval() lets it through only with a signature over
 * this exact request and only once.
 */

function approval_replay_signature(int $id, string $handlerPath, string $bodyJson): string
{
    return hash_hmac('sha256', 'replay:' . $id . '.' . $handlerPath . '.' . hash('sha256', $bodyJson), action_token_key());
}

/** The stored body in one canonical spelling, so the signer and the verifier hash the same bytes. */
function approval_canonical_body(array $body): string
{
    $sort = static function (array &$a) use (&$sort): void {
        ksort($a);
        foreach ($a as &$v) {
            if (is_array($v)) {
                $sort($v);
            }
        }
    };
    $sort($body);
    return json_encode($body, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
}

/**
 * Is THIS request the approved replay of $actionKey? Returns the approval request row when the
 * signature verifies, the row is approved, the action, path, body and caller all match — and the
 * one-use claim is won. Otherwise null, and the caller is paused like anyone else.
 */
function approval_replay_verify(PDO $pdo, string $actionKey): ?array
{
    $header = (string) ($_SERVER['HTTP_X_APPROVAL_REPLAY'] ?? '');
    if ($header === '' || !preg_match('/^(\d+)\.([0-9a-f]{64})$/', $header, $m)) {
        return null;
    }
    $row = find_approval_request($pdo, (int) $m[1]);
    $path = parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH) ?: '';
    $body = approval_canonical_body(array_diff_key($_POST, ['csrf_token' => true]));
    if ($row === null || $row['status'] !== 'approved' || $row['action_key'] !== $actionKey
        || $row['handler_path'] !== $path
        || (int) $row['requested_by_member_id'] !== current_member_id()
        || !hash_equals(approval_replay_signature((int) $row['id'], $path, $body), $m[2])
        || $body !== approval_canonical_body(json_decode((string) $row['request_body'], true) ?: [])) {
        return null;
    }
    return claim_approval_execution($pdo, (int) $row['id']) ? $row : null;
}

/** @return array{ok:bool, error:?string, did:?string} Run the approved request through its handler. */
function replay_approved_request(array $row): array
{
    $path = (string) ($row['handler_path'] ?? '');
    $body = json_decode((string) ($row['request_body'] ?? ''), true);
    // A kernel handler is a path on this server; an application's (the approval hook, A7) is an
    // absolute URL, signed over its path so the application verifies with its own REQUEST_URI.
    $absolute = (bool) preg_match('#^https?://[^\s]+\.php$#', $path);
    $sigPath = $absolute ? (string) parse_url($path, PHP_URL_PATH) : $path;
    if ($path === '' || !is_array($body) || (!$absolute && (!preg_match('#^/[A-Za-z0-9_\-/]+\.php$#', $path) || str_contains($path, '..')))) {
        return ['ok' => false, 'did' => null,
                'error' => 'This request was recorded before approvals could replay an action; ask for it again.'];
    }
    $canonical = approval_canonical_body($body);
    // Back to THIS server. Since the React cut-over PHP answers only on a localhost port of its own
    // (:8080) and port 80 is the React app, which would answer a replay with a redirect. The port
    // serving this very request is by definition the PHP one, so no setting can drift out of date.
    $base = rtrim((string) env('PHP_INTERNAL_BASE', 'http://127.0.0.1:' . (int) ($_SERVER['SERVER_PORT'] ?? 8080)), '/');
    $ch = curl_init($absolute ? $path : $base . $path);
    curl_setopt_array($ch, [
        CURLOPT_POST => true, CURLOPT_POSTFIELDS => http_build_query($body), CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HEADER => true, CURLOPT_FOLLOWLOCATION => false, CURLOPT_CONNECTTIMEOUT => 3, CURLOPT_TIMEOUT => 60,
        CURLOPT_HTTPHEADER => [
            'X-Action-Token: ' . mint_action_token((int) $row['requested_by_member_id'], 120),
            'X-Approval-Replay: ' . $row['id'] . '.' . approval_replay_signature((int) $row['id'], $sigPath, $canonical),
            'Accept: application/json',   // JSON mode, as the actions server calls handlers since the cut-over
        ],
    ]);
    $raw = curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $headerSize = (int) curl_getinfo($ch, CURLINFO_HEADER_SIZE);
    curl_close($ch);
    if ($raw === false) {
        return ['ok' => false, 'did' => null, 'error' => 'The action could not be reached to run it.'];
    }
    $headers = substr((string) $raw, 0, $headerSize);
    $json = json_decode(substr((string) $raw, $headerSize), true);
    // JSON mode answers {ok:true, did…} · 202 {status: pending_approval} · 4xx {error:{message, errors}};
    // the X-Action-* headers say the same and are the fallback when a handler answered no JSON.
    if (is_array($json)) {
        if (($json['ok'] ?? null) === true) {
            return ['ok' => true, 'error' => null, 'did' => isset($json['did']) ? (string) $json['did'] : null];
        }
        $err = is_array($json['error'] ?? null) ? $json['error'] : [];
        $why = ($json['status'] ?? null) === 'pending_approval'
            ? 'The action asked for approval again instead of running.'
            : ($err['errors'] ?? ($err['message'] ?? null));
    } else {
        $status = preg_match('/^x-action-status:\s*(\S+)/mi', $headers, $m) ? strtolower($m[1]) : null;
        $data = preg_match('/^x-action-data:\s*(.+)$/mi', $headers, $d) ? (json_decode(trim($d[1]), true) ?: []) : [];
        if ($status === 'ok') {
            return ['ok' => true, 'error' => null, 'did' => isset($data['did']) ? (string) $data['did'] : null];
        }
        $why = ($data['status'] ?? null) === 'pending_approval'
            ? 'The action asked for approval again instead of running.'
            : ($data['errors'] ?? ($data['error'] ?? null));
    }
    return ['ok' => false, 'did' => null,
            'error' => is_array($why) ? implode(' ', $why) : (string) ($why ?? ('The action answered HTTP ' . $code . '.'))];
}
