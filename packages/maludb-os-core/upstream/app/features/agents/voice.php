<?php
declare(strict_types=1);

/**
 * Voice agents and the telephony provider (RetellAI).
 *
 * Retell's inbound-call webhook is the whole integration for now: when a call reaches one of
 * our numbers, Retell POSTs `{event: "call_inbound", call_inbound: {call_id, from_number,
 * to_number, agent_id, ...}}` and reads a JSON answer within ten seconds. The answer may carry
 * `dynamic_variables`, which is how the agent's own system prompt reaches the call: the Retell
 * agent's template references `{{system_prompt}}`, and we fill it per call from the agent's
 * live configuration version. Retell has no field for a raw prompt, so this is the supported
 * route rather than a workaround.
 *
 * Two things this file does NOT do, deliberately:
 *   - hold the caller. Retell retries on failure, so every path answers quickly and never
 *     waits on anything slow;
 *   - hijack a call it cannot explain. An unknown number, or an agent that is not active,
 *     answers with an empty object, which leaves Retell's own configuration in charge. Cutting
 *     a customer off is a bigger decision than declining to override.
 */

/** Where the signed request must come from, and with what key. */
function retell_api_key(): string
{
    return (string) env('RETELL_API_KEY', '');
}

/**
 * Verify Retell's signature: header `X-Retell-Signature: v={timestamp_ms},d={hex}`, where the
 * digest is HMAC-SHA256 of (raw body . timestamp) keyed with the API key. The timestamp must be
 * recent, or a captured request could be replayed at leisure.
 *
 * @return string|null the reason it failed, or null when the request is authentic.
 */
function retell_signature_failure(string $rawBody, string $header, string $key, int $toleranceSeconds = 300): ?string
{
    if ($key === '') {
        return 'RETELL_API_KEY is not configured';
    }
    if (preg_match('/^v=(\d+),d=([0-9a-f]+)$/i', trim($header), $m) !== 1) {
        return 'malformed or missing X-Retell-Signature';
    }
    [, $timestamp, $digest] = $m;

    // Retell sends milliseconds; compare in seconds so clock drift reads the same either way.
    $sentAt = (int) ((int) $timestamp / 1000);
    if (abs(time() - $sentAt) > $toleranceSeconds) {
        return 'signature timestamp is outside the ' . $toleranceSeconds . 's window';
    }

    $expected = hash_hmac('sha256', $rawBody . $timestamp, $key);
    return hash_equals($expected, strtolower($digest)) ? null : 'signature does not match';
}

/**
 * The voice agent that answers this number, with the prompt the call should run on.
 *
 * Read straight from the base tables rather than the mcp_* views: a webhook carries no member
 * session, so app_is_insider() is false and every view would answer empty. The request is
 * authenticated by signature instead, and this reads exactly one agent by exactly one number.
 */
function voice_agent_for_number(PDO $pdo, string $toNumber): ?array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT ap.member_id, ap.status, ap.phone_number, ap.role_key, ap.description,
               m.display_name, m.job_title,
               v.id AS config_version_id, v.version_no, v.job_description,
               v.system_prompt_id, v.system_prompt_version
          FROM agent_profiles ap
          JOIN members m ON m.id = ap.member_id
          LEFT JOIN agent_config_versions v ON v.id = ap.current_config_version_id
         WHERE ap.phone_number = :num AND ap.agent_kind = 'voice'
    SQL);
    $st->execute(['num' => $toNumber]);
    $row = $st->fetch();
    return $row === false ? null : $row;
}

/**
 * What Retell is told. The prompt is the resolved copy held on the agent's ACTIVE configuration
 * version (db/070's rule: the version records what it actually used, so editing a library
 * prompt later never changes what a past call ran on). An agent with no active version has
 * nothing to answer with, which the caller treats as "no override".
 */
function retell_inbound_response(array $agent, string $businessName): array
{
    $prompt = trim((string) ($agent['job_description'] ?? ''));
    if ($prompt === '') {
        return [];
    }
    return [
        'dynamic_variables' => [
            'system_prompt' => $prompt,
            'agent_name' => (string) $agent['display_name'],
            'agent_job_title' => (string) ($agent['job_title'] ?? ''),
            'business_name' => $businessName,
        ],
        // Correlation, so a call in Retell's console can be found in our activity trail.
        'metadata' => [
            'agent_member_id' => (int) $agent['member_id'],
            'config_version_id' => (int) ($agent['config_version_id'] ?? 0),
            'version_no' => (int) ($agent['version_no'] ?? 0),
        ],
    ];
}
