<?php
declare(strict_types=1);

/**
 * What tools does an MCP endpoint offer right now? Asked of the server itself, so a tool grant
 * can be checked against names that exist (docs/build-specs/agent-runtime-hermes.md, "Tools and
 * grants"). Enforcement is server-side either way — a misspelt grant grants nothing — but the
 * person granting should be told at the form, not find out when the agent cannot work.
 *
 * Only the platform's own servers are asked: the caller's action token is the credential, and a
 * token that acts as a member is never sent to a machine we do not run. For any other endpoint
 * this answers null ("cannot say"), and the grant is saved unchecked.
 */

/** @return list<string>|null  null = this endpoint cannot be asked (not ours, or not answering) */
function mcp_endpoint_tool_names(array $endpoint, int $asMemberId): ?array
{
    $url = (string) ($endpoint['url'] ?? '');
    $host = strtolower((string) parse_url($url, PHP_URL_HOST));
    if (($endpoint['kind'] ?? '') !== 'mcp' || !in_array($host, ['127.0.0.1', 'localhost'], true)) {
        return null;
    }
    $token = mint_action_token($asMemberId, 60);

    $init = mcp_tools_rpc($url, $token, null, [
        'jsonrpc' => '2.0', 'id' => 1, 'method' => 'initialize',
        'params' => [
            'protocolVersion' => '2025-03-26', 'capabilities' => new stdClass(),
            'clientInfo' => ['name' => 'business-os-grant-check', 'version' => '1'],
        ],
    ]);
    if ($init === null) {
        return null;
    }
    $session = $init['session'];
    mcp_tools_rpc($url, $token, $session, ['jsonrpc' => '2.0', 'method' => 'notifications/initialized']);

    $names = [];
    $cursor = null;
    for ($page = 0; $page < 20; $page++) {   // a server that pages forever is not answering
        $list = mcp_tools_rpc($url, $token, $session, [
            'jsonrpc' => '2.0', 'id' => 2 + $page, 'method' => 'tools/list',
            'params' => $cursor === null ? new stdClass() : ['cursor' => $cursor],
        ]);
        if ($list === null || !is_array($list['result']['tools'] ?? null)) {
            return null;
        }
        foreach ($list['result']['tools'] as $tool) {
            if (is_string($tool['name'] ?? null)) {
                $names[] = $tool['name'];
            }
        }
        $cursor = $list['result']['nextCursor'] ?? null;
        if (!is_string($cursor) || $cursor === '') {
            break;
        }
    }
    return $names;
}

/**
 * One streamable-HTTP exchange. The answer comes back as JSON or as one SSE `data:` line,
 * whichever the server chose. @return array{session: ?string, result: array}|null
 */
function mcp_tools_rpc(string $url, string $token, ?string $session, array $message): ?array
{
    $headers = [
        'Content-Type: application/json',
        'Accept: application/json, text/event-stream',
        'Authorization: Bearer ' . $token,
    ];
    if ($session !== null) {
        $headers[] = 'Mcp-Session-Id: ' . $session;
    }
    $seen = null;
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => json_encode($message, JSON_THROW_ON_ERROR),
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_CONNECTTIMEOUT => 2,
        CURLOPT_TIMEOUT => 5,
        CURLOPT_HEADERFUNCTION => static function ($ch, string $line) use (&$seen): int {
            if (stripos($line, 'mcp-session-id:') === 0) {
                $seen = trim(substr($line, 15));
            }
            return strlen($line);
        },
    ]);
    $body = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    if (!is_string($body) || $status < 200 || $status >= 300) {
        return null;
    }
    if (!isset($message['id'])) {
        return ['session' => $seen ?? $session, 'result' => []];   // a notification has no answer
    }
    $decoded = json_decode($body, true);
    if (!is_array($decoded)) {
        foreach (preg_split('/\R/', $body) ?: [] as $line) {
            if (str_starts_with($line, 'data:')) {
                $try = json_decode(trim(substr($line, 5)), true);
                if (is_array($try) && ($try['id'] ?? null) === $message['id']) {
                    $decoded = $try;
                    break;
                }
            }
        }
    }
    if (!is_array($decoded) || !is_array($decoded['result'] ?? null)) {
        return null;
    }
    return ['session' => $seen ?? $session, 'result' => $decoded['result']];
}

/** The refusal sentence for a name the endpoint does not offer — with the near misses, so a
 *  typo is fixed in one go. */
function mcp_unknown_tool_message(string $tool, string $endpointLabel, array $names): string
{
    $near = [];
    foreach ($names as $name) {
        if (str_contains($name, $tool) || str_contains($tool, $name) || levenshtein($tool, $name) <= 3) {
            $near[] = $name;
        }
    }
    sort($near);
    $hint = $near !== []
        ? ' Did you mean: ' . implode(', ', array_slice($near, 0, 5)) . '?'
        : ' Tool names are as the server reports them, e.g. ' . implode(', ', array_slice($names, 0, 3)) . '.';
    return '"' . $tool . '" is not a tool on ' . $endpointLabel . '.' . $hint;
}
