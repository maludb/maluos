<?php
declare(strict_types=1);

/**
 * Activity screen queries (manifest screen `activity`). Reads mcp_activity_business, which
 * applies the same visibility rules the activity MCP server answers through — so the trail a
 * person reads on screen is the trail their agent can quote back to them.
 */

const ACTIVITY_PAGE_SIZE = 50;
const ACTIVITY_PERIODS = ['today', 'this_week', 'this_month', 'last_30_days', 'all'];

function activity_period_bounds(string $period): ?array
{
    return match ($period) {
        'today' => ['current_date', 'current_date + 1'],
        'this_week' => ["date_trunc('week', current_date)", "date_trunc('week', current_date) + interval '1 week'"],
        'this_month' => ["date_trunc('month', current_date)", "date_trunc('month', current_date) + interval '1 month'"],
        'last_30_days' => ['current_date - 30', 'current_date + 1'],
        default => null,
    };
}

/**
 * The activity stream, filtered. `entity_type` + `entity_id` narrow it to one record's
 * history — which is what "what happened to this deal?" means.
 */
function find_activity(
    PDO $pdo,
    string $entityType = '',
    ?int $entityId = null,
    ?int $memberId = null,
    string $source = '',
    string $period = 'last_30_days',
    bool $includeViews = false,
    int $page = 1
): array {
    $where = [];
    $params = [];

    if ($entityType !== '') {
        $where[] = 'entity_type = :etype';
        $params['etype'] = $entityType;
    }
    if ($entityId !== null) {
        $where[] = 'entity_id = :eid';
        $params['eid'] = $entityId;
    }
    if ($memberId !== null) {
        $where[] = 'actor_member_id = :actor';
        $params['actor'] = $memberId;
    }
    if ($source !== '') {
        $where[] = 'source = :source';
        $params['source'] = $source;
    }
    if (!$includeViews) {
        $where[] = "action <> 'screen.view'";
    }
    $bounds = activity_period_bounds($period);
    if ($bounds !== null) {
        $where[] = "occurred_at >= {$bounds[0]} AND occurred_at < {$bounds[1]}";
    }
    $whereSql = $where === [] ? '' : 'WHERE ' . implode(' AND ', $where);
    $offset = (max(1, $page) - 1) * ACTIVITY_PAGE_SIZE;

    $st = $pdo->prepare("
        SELECT id, occurred_at, actor_member_id, actor_name, actor_kind, source, action,
               entity_type, entity_id, before, after, count(*) OVER() AS total_count,
               app_record_label(entity_type, entity_id) AS entity_label   -- the record's name (db/152), else NULL
          FROM mcp_activity_business
          {$whereSql}
         ORDER BY id DESC
         LIMIT :lim OFFSET :off
    ");
    foreach ($params as $key => $value) {
        $st->bindValue($key, $value);
    }
    $st->bindValue('lim', ACTIVITY_PAGE_SIZE, PDO::PARAM_INT);
    $st->bindValue('off', $offset, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}

/** Who has been active, for the filter. */
function activity_actors(PDO $pdo): array
{
    return $pdo->query(<<<'SQL'
        SELECT DISTINCT actor_member_id AS member_id, actor_name AS display_name
          FROM mcp_activity_business
         WHERE actor_member_id IS NOT NULL
         ORDER BY actor_name
         LIMIT 100
    SQL)->fetchAll();
}

/** The entity kinds that actually appear in the trail, for the filter. */
function activity_entity_types(PDO $pdo): array
{
    return $pdo->query(<<<'SQL'
        SELECT DISTINCT entity_type
          FROM mcp_activity_business
         WHERE entity_type IS NOT NULL
         ORDER BY entity_type
    SQL)->fetchAll(PDO::FETCH_COLUMN);
}
