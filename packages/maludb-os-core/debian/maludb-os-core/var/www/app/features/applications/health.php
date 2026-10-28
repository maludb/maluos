<?php
declare(strict_types=1);

/**
 * Health checks (build spec: docs/build-specs/applications.md, "Health checks").
 *
 * Only mcp, http_api and ui endpoints are checkable from here — a short-timeout (3s) HTTP
 * request to the endpoint's url, following no redirects. database, filesystem, smtp, imap, ssh
 * and webhook are never guessed at: "not checkable from the platform" is the honest answer, and
 * an application with no checkable endpoint is 'unknown', never 'up'. Checks run on demand only
 * in this slice; the scheduled checker is a cron job the manifest lists under "written by the
 * system" — noted, not built here.
 */

const ENDPOINT_CHECKABLE_KINDS = ['mcp', 'http_api', 'ui'];

/**
 * One endpoint's reachability. Pure-ish: no DB access, just an HTTP probe.
 * up       — 2xx/3xx, or 401/403 (reachable and asking for auth IS up)
 * down     — connection failure, or 5xx (and any other non-2xx/3xx/401/403 status: the spec
 *            fixes only those two buckets, so an unlisted code is treated as not-up rather than
 *            guessed at as healthy)
 * degraded — timed out
 * unknown  — not a checkable kind, or no URL recorded to check
 */
function check_endpoint(string $url, string $kind): array
{
    if (!in_array($kind, ENDPOINT_CHECKABLE_KINDS, true)) {
        return ['status' => 'unknown', 'detail' => 'not checkable from the platform'];
    }
    if (trim($url) === '') {
        return ['status' => 'unknown', 'detail' => 'no URL recorded to check'];
    }

    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 3,
        CURLOPT_TIMEOUT => 3,
        CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_NOBODY => false,
    ]);
    curl_exec($ch);
    $errno = curl_errno($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($errno === CURLE_OPERATION_TIMEDOUT) {
        return ['status' => 'degraded', 'detail' => 'timed out after 3s'];
    }
    if ($errno !== 0) {
        return ['status' => 'down', 'detail' => 'connection failed'];
    }
    if (($code >= 200 && $code < 400) || $code === 401 || $code === 403) {
        return ['status' => 'up', 'detail' => 'HTTP ' . $code];
    }
    return ['status' => 'down', 'detail' => 'HTTP ' . $code];
}

/**
 * An application's health is the worst of its checkable endpoints, and 'unknown' when it has
 * none — never invent 'up'. Writes health_status + last_health_check_at (the timestamp is
 * written even when nothing was checkable: "we asked, there was nothing to check" is itself a
 * fact worth recording).
 */
function check_application_health(PDO $pdo, int $id): array
{
    $st = $pdo->prepare("
        SELECT id, name, kind, url FROM application_endpoints
         WHERE application_id = :id AND status = 'active' AND kind = ANY(:kinds)
    ");
    $st->execute(['id' => $id, 'kinds' => pg_array_literal_text(ENDPOINT_CHECKABLE_KINDS)]);
    $endpoints = $st->fetchAll();

    $severity = ['up' => 0, 'degraded' => 1, 'down' => 2];
    $worst = null;
    $checkedCount = 0;
    $details = [];
    foreach ($endpoints as $ep) {
        $result = check_endpoint((string) ($ep['url'] ?? ''), (string) $ep['kind']);
        if ($result['status'] === 'unknown') {
            continue; // no URL to check — does not count toward the verdict
        }
        $checkedCount++;
        $details[] = $ep['name'] . ': ' . $result['status'];
        if ($worst === null || $severity[$result['status']] > $severity[$worst]) {
            $worst = $result['status'];
        }
    }

    $status = $worst ?? 'unknown';
    $detail = $checkedCount === 0
        ? 'not checkable from the platform'
        : $status . ' (' . implode(', ', $details) . ')';

    $upd = $pdo->prepare('UPDATE applications SET health_status = :status, last_health_check_at = now()
                           WHERE id = :id');
    $upd->execute(['status' => $status, 'id' => $id]);

    return ['health_status' => $status, 'detail' => $detail, 'checked_count' => $checkedCount];
}

/** Render a PHP string[] as a PostgreSQL text[] literal for kind = ANY(:kinds). */
function pg_array_literal_text(array $values): string
{
    $escaped = array_map(static fn (string $v): string => '"' . str_replace('"', '\\"', $v) . '"', $values);
    return '{' . implode(',', $escaped) . '}';
}
