<?php
declare(strict_types=1);

/**
 * Activity (screen id `activity`) — the trail of what happened, filterable to one record's
 * history. Gate: any signed-in member; the view decides which rows they see.
 */
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/activity/queries.php';

require_login();

$pdo = db();
$entityType = request_string('entity_type');
$entityId = request_integer('entity_id');
$memberId = request_integer('member');
$source = request_string('source');
$period = request_string('period', 'last_30_days');
$period = in_array($period, ACTIVITY_PERIODS, true) ? $period : 'last_30_days';
$includeViews = request_bool('views');
$page = request_integer('page') ?? 1;

$rows = find_activity($pdo, $entityType, $entityId, $memberId, $source, $period, $includeViews, $page);
$total = (int) ($rows[0]['total_count'] ?? 0);
$totalPages = max(1, (int) ceil($total / ACTIVITY_PAGE_SIZE));
$filters = [
    'entity_type' => $entityType, 'entity_id' => $entityId, 'member' => $memberId,
    'source' => $source, 'period' => $period, 'views' => $includeViews,
];
$viewerTz = current_member()['timezone'] ?? 'UTC';

if (($_SERVER['HTTP_HX_TARGET'] ?? '') === 'activity-results') {
    header('Vary: HX-Request');
    echo view('activity/partials/table.php',
        ['rows' => $rows, 'page' => $page, 'totalPages' => $totalPages,
         'viewerTz' => $viewerTz, 'filters' => $filters]);
    exit;
}

log_screen_view($pdo, 'activity');
if (wants_json()) {
    require_once dirname(__DIR__) . '/app/features/activity/present.php';
    respond_screen([
        'rows' => array_map('present_activity_row', $rows),
        'pagination' => ['page' => $page, 'total_pages' => $totalPages, 'total' => $total],
        'filters' => [
            'period' => $period, 'source' => $source,
            'member' => $memberId === null ? '' : (string) $memberId,
            'entity_type' => $entityType,
            'entity_id' => $entityId === null ? '' : (string) $entityId,
            'views' => $includeViews,
        ],
        'options' => [
            'actors' => array_map('present_activity_actor', activity_actors($pdo)),
            'entity_types' => array_values(activity_entity_types($pdo)),
        ],
    ]);
}
render_screen('Activity · ' . business_name($pdo), view('activity/page.php', [
    'rows' => $rows, 'filters' => $filters, 'actors' => activity_actors($pdo),
    'entityTypes' => activity_entity_types($pdo), 'page' => $page, 'totalPages' => $totalPages,
    'viewerTz' => $viewerTz,
]), ['activeNav' => 'nav-dashboard', 'screen' => 'activity']);
