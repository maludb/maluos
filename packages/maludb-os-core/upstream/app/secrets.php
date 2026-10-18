<?php
declare(strict_types=1);

/**
 * The tenant secrets store — the first writer of `tenant_secrets` (design decided 2026-09-18,
 * docs/business-os-questions.md: AES-256-GCM, `SECRETS_KEY` in config/.env, `key_version` and
 * `last4` kept for rotation and display). Built as groundwork for the stubbed modules
 * (docs/build-specs/stub-modules-decisions.md): a mailbox password, a provider credential, a
 * channel token. The rule it serves: a record carries a REFERENCE to a secret (its id), never
 * the secret (docs/business-os-schema.md, decision 18).
 *
 * Stored form: "v<key_version>:" . base64(iv[12] . tag[16] . ciphertext). The secret's NAME is
 * bound in as additional authenticated data, so a ciphertext copied onto another row does not
 * decrypt. Plain text is never logged, never returned by a presenter, and never leaves this
 * file except from read_tenant_secret() — whose callers are handlers and jobs that must USE the
 * credential. The records MCP role has no grant on this table.
 *
 * The Python jobs read the same format (mcp/secrets_store.py).
 */

const TENANT_SECRET_PURPOSES = ['model_provider', 'payment_provider', 'channel', 'email', 'application', 'other'];

/** The 32-byte key for a key version. v1 is SECRETS_KEY; a rotation adds SECRETS_KEY_V2, … */
function secrets_key(int $version = 1): string
{
    $hex = (string) env($version === 1 ? 'SECRETS_KEY' : 'SECRETS_KEY_V' . $version, '');
    if (strlen($hex) !== 64 || !ctype_xdigit($hex)) {
        throw new RuntimeException('The secrets key (version ' . $version . ') is not configured.');
    }
    return (string) hex2bin($hex);
}

function secrets_current_key_version(): int
{
    return max(1, (int) env('SECRETS_KEY_VERSION', '1'));
}

function encrypt_tenant_secret(string $name, string $plain, int $version): string
{
    $iv = random_bytes(12);
    $tag = '';
    $cipher = openssl_encrypt($plain, 'aes-256-gcm', secrets_key($version), OPENSSL_RAW_DATA, $iv, $tag, $name, 16);
    if ($cipher === false) {
        throw new RuntimeException('The secret could not be encrypted.');
    }
    return 'v' . $version . ':' . base64_encode($iv . $tag . $cipher);
}

function decrypt_tenant_secret(string $name, string $stored): string
{
    if (!preg_match('/^v(\d+):(.+)$/s', $stored, $m)) {
        throw new RuntimeException('Unreadable secret.');
    }
    $raw = base64_decode($m[2], true);
    if ($raw === false || strlen($raw) < 29) {
        throw new RuntimeException('Unreadable secret.');
    }
    $plain = openssl_decrypt(substr($raw, 28), 'aes-256-gcm', secrets_key((int) $m[1]), OPENSSL_RAW_DATA,
        substr($raw, 0, 12), substr($raw, 12, 16), $name);
    if ($plain === false) {
        throw new RuntimeException('The secret could not be decrypted.');
    }
    return $plain;
}

/**
 * Store a secret under a unique name, or rotate the one already there. Returns its id — the
 * reference a record keeps. `last4` is what a screen may show so a person can tell two keys apart.
 */
function store_tenant_secret(PDO $pdo, string $name, string $purpose, ?string $provider, string $plain, ?int $createdBy): int
{
    if (!in_array($purpose, TENANT_SECRET_PURPOSES, true)) {
        throw new InvalidArgumentException('Unknown secret purpose.');
    }
    if ($name === '' || $plain === '') {
        throw new InvalidArgumentException('A secret needs a name and a value.');
    }
    $version = secrets_current_key_version();
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO tenant_secrets (name, purpose, provider, ciphertext, key_version, last4, created_by)
        VALUES (:name, :purpose, :provider, :cipher, :ver, :last4, :by)
        ON CONFLICT (name) DO UPDATE
           SET ciphertext = EXCLUDED.ciphertext, key_version = EXCLUDED.key_version,
               last4 = EXCLUDED.last4, provider = EXCLUDED.provider,
               rotated_at = now(), revoked_at = NULL, updated_at = now()
        RETURNING id
    SQL);
    $st->execute([
        'name' => $name, 'purpose' => $purpose, 'provider' => $provider,
        'cipher' => encrypt_tenant_secret($name, $plain, $version), 'ver' => $version,
        'last4' => mb_strlen($plain) >= 8 ? mb_substr($plain, -4) : null,
        'by' => $createdBy,
    ]);
    return (int) $st->fetchColumn();
}

/** The plain secret, for code that must use it. NULL when it does not exist or was revoked. */
function read_tenant_secret(PDO $pdo, int $id): ?string
{
    $st = $pdo->prepare('SELECT name, ciphertext FROM tenant_secrets WHERE id = :id AND revoked_at IS NULL');
    $st->execute(['id' => $id]);
    $row = $st->fetch();
    return $row === false ? null : decrypt_tenant_secret((string) $row['name'], (string) $row['ciphertext']);
}

/** Revoke: the row stays (what referenced it is still explainable), the value is destroyed. */
function revoke_tenant_secret(PDO $pdo, int $id): bool
{
    $st = $pdo->prepare("UPDATE tenant_secrets SET revoked_at = now(), ciphertext = '', updated_at = now()
                          WHERE id = :id AND revoked_at IS NULL");
    $st->execute(['id' => $id]);
    return $st->rowCount() === 1;
}

/** What a screen may say about a secret — never its value, never its ciphertext. */
function present_tenant_secret(?array $row): ?array
{
    if ($row === null) {
        return null;
    }
    return [
        'id' => (int) $row['id'],
        'name' => (string) $row['name'],
        'provider' => $row['provider'] ?? null,
        'last4' => $row['last4'] ?? null,
        'set_on' => json_ts($row['rotated_at'] ?? $row['created_at'] ?? null),
        'revoked' => ($row['revoked_at'] ?? null) !== null,
    ];
}
