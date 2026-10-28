<?php
declare(strict_types=1);

/**
 * An application's roles, read from the application itself (db/145, 2026-09-27 —
 * docs/build-specs/kernel-application-roles.md).
 *
 * An application from us publishes its roles through its own MCP server: the tool `app_roles`
 * answers {"schema": "os.app-roles/1", "rights": [{key, description}], "roles": [{key, name,
 * description, capability, is_admin, rights: [key…]}]}. The kernel calls it with a 60-second kernel
 * token (mint_kernel_token()), checks the answer, and makes application_roles match: new roles are
 * added, changed ones updated, and a role no longer published is withdrawn — never deleted — so the
 * grants that still hold it can be shown and changed. The application enforces the rights; the
 * kernel shows them, grants roles, and passes the keys on in the claims, the feed and run facts.
 */

const APP_ROLES_TOOL = 'app_roles';
const APP_ROLES_SCHEMA = 'os.app-roles/1';
const MCP_PROTOCOL_VERSION = '2025-06-18';

/**
 * One JSON-RPC message to a streamable-HTTP MCP server. Answers [decoded message or null, the
 * session id header, http status]. A server may answer plain JSON or a short event stream; both are read.
 */
function mcp_http_post(string $url, string $token, array $message, ?string $session, int $timeout = 8, array $extraHeaders = []): array
{
    $headers = array_merge(['Content-Type: application/json', 'Accept: application/json, text/event-stream',
                'Authorization: Bearer ' . $token, 'MCP-Protocol-Version: ' . MCP_PROTOCOL_VERSION], $extraHeaders);
    if ($session !== null) {
        $headers[] = 'Mcp-Session-Id: ' . $session;
    }
    $sessionOut = $session;
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => json_encode($message, JSON_UNESCAPED_SLASHES),
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => $timeout,
        CURLOPT_CONNECTTIMEOUT => 3,
        CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_HEADERFUNCTION => static function ($ch, string $line) use (&$sessionOut): int {
            if (stripos($line, 'mcp-session-id:') === 0) {
                $sessionOut = trim(substr($line, strlen('mcp-session-id:')));
            }
            return strlen($line);
        },
    ]);
    $body = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $type = (string) curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
    curl_close($ch);
    if (!is_string($body) || $body === '') {
        return [null, $sessionOut, $status];
    }
    if (stripos($type, 'text/event-stream') !== false) {
        $found = null;
        foreach (preg_split('/\r?\n/', $body) as $line) {
            if (str_starts_with($line, 'data:')) {
                $msg = json_decode(trim(substr($line, 5)), true);
                if (is_array($msg) && array_key_exists('id', $msg) && ($msg['id'] ?? null) === ($message['id'] ?? null)) {
                    $found = $msg;
                }
            }
        }
        return [$found, $sessionOut, $status];
    }
    $msg = json_decode($body, true);
    return [is_array($msg) ? $msg : null, $sessionOut, $status];
}

/**
 * Call one tool on an MCP server as the kernel. Answers the tool's decoded JSON text, or throws
 * RuntimeException saying what went wrong in words a super-admin can act on.
 */
/**
 * $timeout: seconds to wait for the tool's answer (K26: a share's own, 1–60; the handshake keeps 8). $headers: extra HTTP headers on
 * every message of the call — K26 sends the consumer's identity this way (X-OS-Consumer, X-OS-Consumer-Agent), never in the arguments.
 */
function mcp_call_tool_as_kernel(string $url, string $appKey, string $tool, array $arguments = [], int $timeout = 8, array $headers = []): array
{
    $token = mint_kernel_token($appKey);
    [$init, $session, $status] = mcp_http_post($url, $token, ['jsonrpc' => '2.0', 'id' => 1, 'method' => 'initialize',
        'params' => ['protocolVersion' => MCP_PROTOCOL_VERSION, 'capabilities' => (object) [],
                     'clientInfo' => ['name' => 'business-os-kernel', 'version' => '1']]], null, 8, $headers);
    if ($status === 401 || $status === 403) {
        throw new RuntimeException('The application refused the kernel\'s token at ' . $url . ' — it does not accept kernel calls yet.');
    }
    if ($init === null || isset($init['error'])) {
        throw new RuntimeException('No MCP server answered at ' . $url . ' (HTTP ' . $status . ').');
    }
    mcp_http_post($url, $token, ['jsonrpc' => '2.0', 'method' => 'notifications/initialized'], $session, 8, $headers);
    [$answer] = mcp_http_post($url, $token, ['jsonrpc' => '2.0', 'id' => 2, 'method' => 'tools/call',
        'params' => ['name' => $tool, 'arguments' => (object) $arguments]], $session, max(1, min(60, $timeout)), $headers);
    if ($answer === null) {
        throw new RuntimeException('The MCP server at ' . $url . ' did not answer ' . $tool . '.');
    }
    if (isset($answer['error'])) {
        throw new RuntimeException($url . ' has no ' . $tool . ' tool (' . (string) ($answer['error']['message'] ?? 'error') . ').');
    }
    $result = $answer['result'] ?? [];
    if (!empty($result['isError'])) {
        throw new RuntimeException($tool . ' failed at ' . $url . ': ' . (string) ($result['content'][0]['text'] ?? 'no reason given'));
    }
    if (isset($result['structuredContent']) && is_array($result['structuredContent'])) {
        $structured = $result['structuredContent'];
        // FastMCP wraps a plain string return as {"result": "..."}.
        if (isset($structured['result']) && is_string($structured['result']) && count($structured) === 1) {
            $decoded = json_decode($structured['result'], true);
            if (is_array($decoded)) {
                return $decoded;
            }
        } elseif (isset($structured['schema'])) {
            return $structured;
        }
    }
    $text = (string) ($result['content'][0]['text'] ?? '');
    $decoded = json_decode($text, true);
    if (!is_array($decoded)) {
        throw new RuntimeException($tool . ' at ' . $url . ' did not answer JSON.');
    }
    return $decoded;
}

/**
 * Ask the application for its roles: every live MCP endpoint of the application is tried in order
 * until one answers app_roles. Answers [payload, endpoint name]; throws RuntimeException with every
 * endpoint's reason when none does.
 */
function fetch_application_roles(PDO $pdo, array $application): array
{
    $st = $pdo->prepare("SELECT name, url FROM application_endpoints
                          WHERE application_id = :id AND kind = 'mcp' AND status = 'active' ORDER BY id");
    $st->execute(['id' => (int) $application['application_id']]);
    $endpoints = $st->fetchAll();
    if ($endpoints === []) {
        throw new RuntimeException('This application has no MCP endpoint to ask for its roles — add its records MCP server under Endpoints.');
    }
    $why = [];
    foreach ($endpoints as $e) {
        try {
            return [mcp_call_tool_as_kernel((string) $e['url'], (string) $application['app_key'], APP_ROLES_TOOL), (string) $e['name']];
        } catch (RuntimeException $ex) {
            $why[] = $e['name'] . ': ' . $ex->getMessage();
        }
    }
    throw new RuntimeException('No endpoint answered ' . APP_ROLES_TOOL . ' — ' . implode(' ', $why));
}

/**
 * Check what an application published. Answers [roles, errors]; each role is
 * {key, name, description, capability, is_admin, rights: [{key, description}]}, in the published order.
 */
function validate_application_roles(array $payload): array
{
    $errors = [];
    if (($payload['schema'] ?? null) !== APP_ROLES_SCHEMA) {
        $errors[] = 'The application answered schema ' . json_encode($payload['schema'] ?? null) . ', not ' . APP_ROLES_SCHEMA . '.';
        return [[], $errors];
    }
    $catalog = [];
    foreach (is_array($payload['rights'] ?? null) ? $payload['rights'] : [] as $r) {
        $key = is_array($r) ? (string) ($r['key'] ?? '') : '';
        if (!preg_match('/^[a-z][a-z0-9_.]{0,59}$/', $key)) {
            $errors[] = 'A right key is lowercase letters, digits, dots and underscores: ' . ($key ?: '(empty)') . '.';
            continue;
        }
        $catalog[$key] = ['key' => $key, 'description' => trim((string) ($r['description'] ?? ''))];
    }
    $roles = [];
    foreach (is_array($payload['roles'] ?? null) ? $payload['roles'] : [] as $r) {
        $key = is_array($r) ? strtolower(trim((string) ($r['key'] ?? ''))) : '';
        if (!preg_match('/^[a-z][a-z0-9_]{0,39}$/', $key)) {
            $errors[] = 'A role key is lowercase letters, digits and underscores, starting with a letter: ' . ($key ?: '(empty)') . '.';
            continue;
        }
        if (isset($roles[$key])) {
            $errors[] = 'The role ' . $key . ' is published twice.';
            continue;
        }
        $name = trim((string) ($r['name'] ?? ''));
        $capability = (string) ($r['capability'] ?? '');
        $isAdmin = !empty($r['is_admin']);
        if ($name === '' || mb_strlen($name) > 100) {
            $errors[] = 'The role ' . $key . ' needs a name (up to 100 characters).';
        }
        if (!in_array($capability, ACCESS_CAPABILITIES, true)) {
            $errors[] = 'The role ' . $key . ' amounts to read, write or admin.';
        }
        if ($isAdmin && $capability !== 'admin') {
            $errors[] = 'The admin role ' . $key . ' amounts to admin.';
        }
        $rights = [];
        foreach (is_array($r['rights'] ?? null) ? $r['rights'] : [] as $right) {
            $rk = (string) $right;
            if (!isset($catalog[$rk])) {
                $errors[] = 'The role ' . $key . ' gives ' . ($rk ?: '(empty)') . ', which the application does not list among its rights.';
                continue;
            }
            $rights[$rk] = $catalog[$rk];
        }
        $roles[$key] = ['key' => $key, 'name' => $name, 'description' => trim((string) ($r['description'] ?? '')) ?: null,
                        'capability' => $capability, 'is_admin' => $isAdmin, 'rights' => array_values($rights)];
    }
    if ($roles === []) {
        $errors[] = 'The application published no roles.';
    } elseif (count(array_filter($roles, static fn (array $r): bool => $r['is_admin'])) !== 1) {
        $errors[] = 'Exactly one role must be the admin role — the one a super-admin holds.';
    }
    return [array_values($roles), $errors];
}

/**
 * Make the kernel's copy match what the application published. The caller owns the transaction.
 * Answers ['added' => keys, 'changed' => keys, 'withdrawn' => keys, 'restored' => keys].
 */
function apply_application_roles(PDO $pdo, int $applicationId, array $roles): array
{
    $current = [];
    $st = $pdo->prepare('SELECT * FROM application_roles WHERE application_id = :app');
    $st->execute(['app' => $applicationId]);
    foreach ($st->fetchAll() as $r) {
        $current[(string) $r['role_key']] = $r;
    }
    $outcome = ['added' => [], 'changed' => [], 'withdrawn' => [], 'restored' => []];
    // One admin role at a time: clear the flag before the upsert sets it where it now belongs.
    $pdo->prepare('UPDATE application_roles SET is_admin = false WHERE application_id = :app AND is_admin')
        ->execute(['app' => $applicationId]);
    $up = $pdo->prepare(<<<'SQL'
        INSERT INTO application_roles (application_id, role_key, name, description, capability, is_admin, rights, sort_order)
        VALUES (:app, :key, :name, :descr, :cap, :admin, CAST(:rights AS jsonb), :sort)
        ON CONFLICT (application_id, role_key) DO UPDATE
           SET name = EXCLUDED.name, description = EXCLUDED.description, capability = EXCLUDED.capability,
               is_admin = EXCLUDED.is_admin, rights = EXCLUDED.rights, sort_order = EXCLUDED.sort_order,
               withdrawn_at = NULL
    SQL);
    foreach ($roles as $i => $r) {
        $old = $current[$r['key']] ?? null;
        $rights = json_encode($r['rights'], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        if ($old === null) {
            $outcome['added'][] = $r['key'];
        } elseif ($old['withdrawn_at'] !== null) {
            $outcome['restored'][] = $r['key'];
        } elseif ($old['name'] !== $r['name'] || ($old['description'] ?? null) !== $r['description']
                  || $old['capability'] !== $r['capability'] || (bool) $old['is_admin'] !== $r['is_admin']
                  || json_decode((string) $old['rights'], true) != $r['rights']) {
            $outcome['changed'][] = $r['key'];
        }
        $up->execute(['app' => $applicationId, 'key' => $r['key'], 'name' => $r['name'], 'descr' => $r['description'],
                      'cap' => $r['capability'], 'admin' => $r['is_admin'] ? 't' : 'f', 'rights' => $rights, 'sort' => $i + 1]);
    }
    $published = array_column($roles, 'key');
    $withdraw = $pdo->prepare('UPDATE application_roles SET withdrawn_at = now()
                                WHERE application_id = :app AND role_key = :key AND withdrawn_at IS NULL');
    foreach ($current as $key => $old) {
        if (!in_array($key, $published, true) && $old['withdrawn_at'] === null) {
            $withdraw->execute(['app' => $applicationId, 'key' => $key]);
            $outcome['withdrawn'][] = $key;
        }
    }
    $pdo->prepare('UPDATE applications SET roles_synced_at = now() WHERE id = :app')->execute(['app' => $applicationId]);
    return $outcome;
}

/**
 * The grants on an application that hold a withdrawn role, for the Access tab's warning:
 * [{application_access_id, grantee, role_key, role_name}].
 */
function grants_holding_withdrawn_roles(PDO $pdo, int $applicationId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT x.application_access_id, COALESCE(m.display_name, d.name::text, 'everyone at ' || l.name) AS grantee,
               x.role_key, r.name AS role_name,
               ac.member_id, m.member_kind, ac.department_id, ac.resident_location_id
          FROM application_access_roles x
          JOIN application_access ac ON ac.id = x.application_access_id AND ac.revoked_at IS NULL
          JOIN application_roles r ON r.application_id = x.application_id AND r.role_key = x.role_key AND r.withdrawn_at IS NOT NULL
          LEFT JOIN members m ON m.id = ac.member_id
          LEFT JOIN departments d ON d.id = ac.department_id
          LEFT JOIN locations l ON l.id = ac.resident_location_id
         WHERE x.application_id = :app
         ORDER BY grantee, x.role_key
    SQL);
    $st->execute(['app' => $applicationId]);
    return $st->fetchAll();
}

/** When the roles were last read from the application (db/145), or null. */
function application_roles_synced_at(PDO $pdo, int $applicationId): ?string
{
    $st = $pdo->prepare('SELECT roles_synced_at FROM applications WHERE id = :id');
    $st->execute(['id' => $applicationId]);
    $at = $st->fetchColumn();
    return $at === false || $at === null ? null : (string) $at;
}
