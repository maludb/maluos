<?php
declare(strict_types=1);

/**
 * Memory — what the business knows that the signed-in member may read, and the way in to core
 * memory. JSON only (React). Build spec: docs/build-specs/memory-screen.md.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/memory/maludb.php';
require_once dirname(__DIR__, 2) . '/app/features/memory/scope.php';
require_once dirname(__DIR__, 2) . '/app/features/memory/reads.php';
require_once dirname(__DIR__, 2) . '/app/features/memory/present.php';

require_insider();
$pdo = db();

$query = mb_substr(trim(request_string('q')), 0, 500);
$subject = mb_substr(trim(request_string('subject')), 0, MEMORY_SUBJECT_MAX);
$scope = request_string('scope');
$scope = in_array($scope, ['self', 'department', 'org'], true) ? $scope : null;

$scopes = memory_read_scopes($pdo, $scope);
$results = [];
$note = null;
$unavailable = null;
if (mb_strlen($query) >= 2 && $scopes !== []) {
    [$found, $unavailable] = memory_recall($scopes, $query, $subject !== '' ? $subject : null);
    if ($found !== null) {
        $labels = array_column($scopes, 'label', 'namespace');
        foreach ($found['results'] ?? [] as $r) {
            if (is_array($r) && isset($labels[(string) ($r['namespace'] ?? '')])) {   // never show what was not asked for
                $results[] = present_memory_result($r, $labels);
            }
        }
        $note = is_string($found['note'] ?? null) && $found['note'] !== '' ? $found['note'] : null;
    }
} elseif (mb_strlen($query) >= 2) {
    $note = 'You belong to no department, so there is no department memory to search.';
}

log_screen_view($pdo, 'memory');
respond_screen([
    'search' => ['q' => $query, 'subject' => $subject, 'scope' => $scope ?? 'all', 'asked' => mb_strlen($query) >= 2],
    'searched' => array_column($scopes, 'label'),
    'results' => $results,
    'note' => $note,
    'memory_available' => $unavailable === null,
    'memory_error' => $unavailable,
    'me' => ['member_id' => (int) current_member_id()],
    'agents' => array_map('present_memory_agent_link', memory_openable_agents($pdo)),
    'options' => ['departments' => memory_my_departments($pdo)],
    'can' => ['remember_org' => is_business_admin()],
]);
