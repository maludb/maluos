<?php
declare(strict_types=1);

/**
 * PostgreSQL connection (the app_rw role). A single PDO per request.
 *
 * On first connect we set the RLS request context (app.member_id / app.role) from the
 * session, so every query the app runs is scoped to the signed-in member exactly as the
 * MCP read servers are. Anonymous requests run with an empty member id and role 'anon'.
 */
function db(): PDO
{
    static $pdo = null;
    if ($pdo instanceof PDO) {
        return $pdo;
    }

    $dsn = sprintf(
        'pgsql:host=%s;port=%s;dbname=%s',
        env('DB_HOST', '127.0.0.1'),
        env('DB_PORT', '5432'),
        env('DB_NAME', 'maludb_os')
    );

    $pdo = new PDO($dsn, env('DB_USER', 'app_rw'), (string) env('DB_PASSWORD', ''), [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES   => false,
    ]);

    db_apply_context($pdo);
    return $pdo;
}

/**
 * Set the row-level-security request context on the connection from the session.
 * set_config(..., false) makes it connection-scoped (persists across statements).
 * Call again after login/logout to refresh it on the live connection.
 */
function db_apply_context(PDO $pdo): void
{
    $memberId = isset($_SESSION['member_id']) ? (string) ((int) $_SESSION['member_id']) : '';
    $role     = $_SESSION['member_role'] ?? 'anon';
    if (!in_array($role, ['member', 'organizer', 'anon'], true)) {
        $role = 'anon';
    }
    $stmt = $pdo->prepare('SELECT set_config(?, ?, false), set_config(?, ?, false)');
    $stmt->execute(['app.member_id', $memberId, 'app.role', $role]);
    // Return all timestamptz values as UTC so the app can format them in each viewer's
    // timezone deterministically (events render in the viewer's tz).
    $pdo->exec("SET TIME ZONE 'UTC'");
}

/**
 * A database error in words a person can act on.
 *
 * Our PL/pgSQL triggers RAISE messages written for people ("This orchestrator still manages 2
 * subagents; remove them from its roster first"), and those are worth showing. Everything
 * around them — SQLSTATE, the driver's "Raise exception: 7", the CONTEXT line naming a function
 * and a line number — is noise that has twice reached a screen because an endpoint tried to cut
 * one specific message down with a regex and the message later changed.
 *
 * So: only a P0001 (our own RAISE) is shown, and only the sentence itself. Every other failure
 * gets the caller's fallback, because a constraint name is not an instruction. The full error
 * always goes to the error log either way.
 */
function db_message(Throwable $e, string $fallback): string
{
    error_log('db error: ' . $e->getMessage());
    if (!($e instanceof PDOException) || (string) $e->getCode() !== 'P0001') {
        return $fallback;
    }
    $text = $e->getMessage();
    $at = strpos($text, 'ERROR:');
    if ($at === false) {
        return $fallback;
    }
    $text = substr($text, $at + 6);
    $text = preg_split('/\R|CONTEXT:/', $text)[0] ?? '';
    $text = trim($text);
    return $text === '' ? $fallback : $text;
}
