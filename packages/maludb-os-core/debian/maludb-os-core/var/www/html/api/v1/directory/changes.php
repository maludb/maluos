<?php
declare(strict_types=1);

/**
 * GET /api/v1/directory/changes.php?since=<cursor> — what changed, for the mirror's timer (A4).
 * `since` is the `next` of the previous answer (a UTC timestamp); absent, the whole directory. Rows
 * are current state, not events: a member row carries its status, a membership its left_at, a
 * department its archived_at — the mirror upserts and needs no history. The one thing with no
 * row to carry is a deleted department: `deleted_departments` lists them (id, name, when) from
 * the activity log, since the cursor — or every one ever, on a full answer — and the mirror
 * drops its row. `next` is taken a few seconds back so a change committed late is delivered
 * again rather than lost. Schema os.directory-changes/1, additive within the major version.
 * `scopes` and `access` (db/141) are about the calling application only.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/api/directory.php';

api_require_get();
$application = directory_authenticate();
$pdo = db();

$since = trim((string) ($_GET['since'] ?? ''));
if ($since !== '') {
    try {
        $since = (new DateTimeImmutable($since))->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d H:i:s.uP');
    } catch (Throwable) {
        api_error('invalid', 'since is the next value of an earlier answer (a UTC timestamp).', 422);
    }
}
$next = $pdo->query("SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC' - make_interval(secs => " . DIRECTORY_OVERLAP_SECONDS . "), 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')")->fetchColumn();
$cursor = $since === '' ? null : $since;

api_json([
    'schema' => DIRECTORY_CHANGES_SCHEMA,
    'since' => $since === '' ? null : $since,
    'next' => $next,
    'full' => $cursor === null,
    'members' => directory_members($pdo, $cursor),
    'departments' => directory_departments($pdo, $cursor),
    'memberships' => directory_memberships($pdo, $cursor),
    'deleted_departments' => directory_deleted_departments($pdo, $cursor),
    // db/141, about the calling application only: the sites or departments it serves, and each
    // affected member's whole holding on it (a member with nothing left: capability null, scopes []).
    'scopes' => directory_scopes($pdo, $application['id'], $cursor),
    'access' => directory_access($pdo, $application['id'], $cursor),
]);
