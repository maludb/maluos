<?php
declare(strict_types=1);

/**
 * The one PHP client for MaluDB's shared-memory routes (MaluDB API 0.2.0).
 *
 * MaluDB namespaces are labels, not access control: whoever holds the tenant token reads all of
 * them. The token is in config/.env and is used ONLY here and by the Memory MCP server; scope is
 * decided by the caller of these functions (features/memory/scope.php) from the verified member,
 * before anything is sent.
 *
 * @return array{status:int, body:array} status 0 = MaluDB unreachable
 */
function maludb_request(string $method, string $path, ?array $body = null): array
{
    $base = rtrim((string) env('MALUDB_API_URL', ''), '/');
    $token = (string) env('MALUDB_API_TOKEN', '');
    if ($base === '' || $token === '') {
        throw new RuntimeException('MaluDB is not configured (MALUDB_API_URL, MALUDB_API_TOKEN).');
    }
    $ch = curl_init($base . $path);
    curl_setopt_array($ch, [
        CURLOPT_CUSTOMREQUEST => $method, CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 3, CURLOPT_TIMEOUT => 30,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'Authorization: Bearer ' . $token],
    ]);
    if ($body !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body, JSON_THROW_ON_ERROR | JSON_UNESCAPED_UNICODE));
    }
    $raw = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    $decoded = is_string($raw) ? json_decode($raw, true) : null;
    return ['status' => $raw === false ? 0 : $status, 'body' => is_array($decoded) ? $decoded : []];
}

/** A sentence for the person when MaluDB said no. Never the raw body. */
function maludb_error(array $response): string
{
    if ($response['status'] === 0) {
        return 'Memory is not reachable right now — nothing was stored.';
    }
    return 'Memory refused that: ' . (string) ($response['body']['error']['message'] ?? ('HTTP ' . $response['status']));
}

/** @return array{0:?int,1:?string} [document_id, error] */
function maludb_remember(string $namespace, string $subject, string $text, array $metadata): array
{
    $r = maludb_request('POST', '/v1/memory/remember', [
        'text' => $text, 'subject' => $subject, 'namespace' => $namespace, 'source_type' => 'note', 'metadata' => $metadata,
    ]);
    return $r['status'] === 201 ? [(int) ($r['body']['document_id'] ?? 0), null] : [null, maludb_error($r)];
}

/** @return array{0:?array,1:?string} [entry, error] */
function maludb_profile_set(string $ref, string $key, string $value, ?string $note): array
{
    $r = maludb_request('PUT', '/v1/principals/' . rawurlencode($ref) . '/profile/' . rawurlencode($key),
        ['value' => $value, 'note' => $note]);
    return $r['status'] === 200 ? [$r['body'], null] : [null, maludb_error($r)];
}
