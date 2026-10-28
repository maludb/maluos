<?php
declare(strict_types=1);

/**
 * A small MCP client for PHP — how a REPORT runs a read tool as the person looking at it
 * (docs/build-specs/reports.md). Streamable HTTP to this machine's own MCP servers only.
 *
 * Token mechanics: mcp_open() inserts ONE mcp_access_tokens row for the member (label
 * `report-run`, two minutes to live), and mcp_close() deletes it — call it in a `finally`. Only
 * the sha256 is stored; the raw token lives in the connection array, never leaves this process
 * except to 127.0.0.1, and must never be presented, logged or returned.
 */

const MCP_SERVERS = ['records' => 'http://127.0.0.1:8811/mcp', 'activity' => 'http://127.0.0.1:8812/mcp'];
const MCP_TOKEN_LABEL = 'report-run';

final class McpRefusal extends RuntimeException {}

/** @return array{server: string, url: string, token: string, token_id: int, session: ?string, next_id: int} */
function mcp_open(PDO $pdo, int $memberId, string $server = 'records'): array
{
    if (!isset(MCP_SERVERS[$server])) {
        throw new McpRefusal('Unknown MCP server.');
    }
    $raw = 'mcp_' . bin2hex(random_bytes(24));
    $st = $pdo->prepare("INSERT INTO mcp_access_tokens (member_id, label, token_hash, scope, expires_at)
                         VALUES (:m, :l, :h, 'mcp', now() + interval '2 minutes') RETURNING id");
    $st->execute(['m' => $memberId, 'l' => MCP_TOKEN_LABEL, 'h' => hash('sha256', $raw)]);
    $conn = ['server' => $server, 'url' => MCP_SERVERS[$server], 'token' => $raw, 'token_id' => (int) $st->fetchColumn(), 'session' => null, 'next_id' => 1];
    try {
        mcp_rpc($conn, 'initialize', ['protocolVersion' => '2025-03-26', 'capabilities' => new stdClass(),
            'clientInfo' => ['name' => 'business-os-reports', 'version' => '1']], 8);
        mcp_rpc($conn, 'notifications/initialized', null, 5, true);
    } catch (Throwable $e) {
        mcp_close($pdo, $conn);
        throw $e;
    }
    return $conn;
}

/** End the MCP session (best effort) and delete the token. Safe to call twice. */
function mcp_close(PDO $pdo, array &$conn): void
{
    if (($conn['session'] ?? null) !== null) {
        $ch = curl_init($conn['url']);
        curl_setopt_array($ch, [CURLOPT_CUSTOMREQUEST => 'DELETE', CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 3,
            CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $conn['token'], 'Mcp-Session-Id: ' . $conn['session']]]);
        curl_exec($ch);
        curl_close($ch);
        $conn['session'] = null;
    }
    if (($conn['token_id'] ?? 0) > 0) {
        try {
            $pdo->prepare('DELETE FROM mcp_access_tokens WHERE id = :id AND label = :l')->execute(['id' => $conn['token_id'], 'l' => MCP_TOKEN_LABEL]);
        } catch (Throwable $e) {
            error_log('mcp_close: token ' . $conn['token_id'] . ' not deleted (it expires in two minutes): ' . $e->getMessage());
        }
        $conn['token_id'] = 0;
    }
    $conn['token'] = '';
}

/**
 * One JSON-RPC exchange. The server answers a POST with JSON or with a short SSE stream; both
 * are read. @return array the `result` member ([] for a notification)
 */
function mcp_rpc(array &$conn, string $method, ?array $params, int $timeout = 15, bool $notification = false): array
{
    $message = ['jsonrpc' => '2.0', 'method' => $method];
    if ($params !== null) {
        $message['params'] = $params;
    }
    $id = null;
    if (!$notification) {
        $id = $message['id'] = $conn['next_id']++;
    }
    $headers = ['Authorization: Bearer ' . $conn['token'], 'Content-Type: application/json', 'Accept: application/json, text/event-stream'];
    if ($conn['session'] !== null) {
        $headers[] = 'Mcp-Session-Id: ' . $conn['session'];
    }
    $session = null;
    $ch = curl_init($conn['url']);
    curl_setopt_array($ch, [
        CURLOPT_POST => true, CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => $timeout, CURLOPT_CONNECTTIMEOUT => 3,
        CURLOPT_HTTPHEADER => $headers, CURLOPT_POSTFIELDS => json_encode($message, JSON_THROW_ON_ERROR),
        CURLOPT_HEADERFUNCTION => static function ($ch, string $line) use (&$session): int {
            if (stripos($line, 'mcp-session-id:') === 0) {
                $session = trim(substr($line, 15));
            }
            return strlen($line);
        },
    ]);
    $body = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $errno = curl_errno($ch);
    curl_close($ch);
    if ($errno === CURLE_OPERATION_TIMEDOUT) {
        throw new McpRefusal('It took too long to answer — try a shorter period.');
    }
    if ($errno !== 0 || $body === false) {
        throw new McpRefusal('The records service could not be reached.');
    }
    if ($status === 401 || $status === 403) {
        throw new McpRefusal('The records service did not accept this sign-in.');
    }
    if ($session !== null) {
        $conn['session'] = $session;
    }
    if ($notification) {
        return [];
    }
    $reply = null;
    $candidates = str_contains((string) $body, 'data:') ? array_map(static fn (string $l): string => ltrim(substr($l, 5)), array_filter(preg_split('/\R/', (string) $body) ?: [], static fn (string $l): bool => str_starts_with($l, 'data:'))) : [(string) $body];
    foreach ($candidates as $json) {
        $decoded = json_decode($json, true);
        if (is_array($decoded) && ($decoded['id'] ?? null) === $id) {
            $reply = $decoded;
        }
    }
    if ($reply === null) {
        throw new McpRefusal('The records service gave no answer (HTTP ' . $status . ').');
    }
    if (isset($reply['error'])) {
        throw new McpRefusal(mcp_plain_error((string) ($reply['error']['message'] ?? 'The records service refused that.')));
    }
    return (array) ($reply['result'] ?? []);
}

/** Every tool the server lists for this caller: name, title, description, read-only?, the params schema. */
function mcp_tools_list(array &$conn): array
{
    $tools = [];
    $cursor = null;
    do {
        $page = mcp_rpc($conn, 'tools/list', $cursor !== null ? ['cursor' => $cursor] : null, 15);
        foreach ((array) ($page['tools'] ?? []) as $t) {
            $schema = (array) ($t['inputSchema'] ?? []);
            // FastMCP wraps a pydantic model as {"properties": {"params": {"$ref": "#/$defs/XIn"}}}.
            $ref = $schema['properties']['params']['$ref'] ?? null;
            $wrapped = $ref !== null;
            $model = $wrapped ? (array) ($schema['$defs'][basename((string) $ref)] ?? []) : $schema;
            $tools[] = [
                'name' => (string) $t['name'], 'title' => (string) ($t['annotations']['title'] ?? $t['title'] ?? $t['name']),
                'description' => trim((string) ($t['description'] ?? '')), 'read_only' => !empty($t['annotations']['readOnlyHint']),
                'wrapped' => $wrapped, 'properties' => (array) ($model['properties'] ?? []), 'required' => array_values((array) ($model['required'] ?? [])),
            ];
        }
        $cursor = $page['nextCursor'] ?? null;
    } while ($cursor !== null);
    return $tools;
}

/**
 * Call a tool. @return mixed the tool's answer, decoded (rows, or an object)
 * @throws McpRefusal with a sentence a person can read — a tool error is never a 500.
 */
function mcp_tool_call(array &$conn, string $tool, array $arguments, bool $wrapped = true, int $timeout = 20): mixed
{
    $args = $wrapped ? ['params' => $arguments === [] ? new stdClass() : $arguments] : ($arguments === [] ? new stdClass() : $arguments);
    $result = mcp_rpc($conn, 'tools/call', ['name' => $tool, 'arguments' => $args], $timeout);
    $text = '';
    foreach ((array) ($result['content'] ?? []) as $part) {
        if (($part['type'] ?? '') === 'text') {
            $text .= (string) $part['text'];
        }
    }
    if (!empty($result['isError'])) {
        throw new McpRefusal(mcp_plain_error($text));
    }
    $decoded = json_decode($text, true);
    if (!is_array($decoded)) {
        throw new McpRefusal($text !== '' ? mb_substr($text, 0, 300) : 'The tool gave no answer.');
    }
    if (isset($decoded['error']) && is_string($decoded['error']) && count($decoded) <= 2) {
        throw new McpRefusal($decoded['error']);
    }
    return $decoded;
}

/** A pydantic / FastMCP error in words: which parameter, what is wrong — no URLs, no class names. */
function mcp_plain_error(string $raw): string
{
    if (preg_match('/Unknown tool/i', $raw)) {
        return 'That tool does not exist any more.';
    }
    if (preg_match_all('/^(?:params\.)?([a-z_0-9.]+)\s*\R\s+(.+?)\s*\[type=/mi', $raw, $m, PREG_SET_ORDER)) {
        return implode(' ', array_map(static fn (array $x): string => 'Parameter “' . $x[1] . '”: ' . rtrim($x[2], '.') . '.', array_slice($m, 0, 4)));
    }
    $raw = trim((string) preg_replace('/^Error executing tool \S+:\s*/', '', $raw));
    $raw = (string) preg_replace('~\s*For further information visit \S+~', '', $raw);
    return mb_substr($raw !== '' ? $raw : 'The tool refused that.', 0, 300);
}
