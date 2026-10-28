<?php
declare(strict_types=1);

/**
 * The menu as data (db/127–129; docs/build-specs/data-driven-nav.md). What a MEMBER sees is
 * app_nav(), asked by nav_modules() in app/business.php; these functions are the super-admin's
 * view of the whole arrangement, and the writes that change it.
 */

const NAV_STATUSES = ['active', 'hidden', 'disabled'];
const NAV_STATUS_LABELS = ['active' => 'Active', 'hidden' => 'Hidden', 'disabled' => 'Disabled'];

/** Every group in order, each with every entry in order — whatever its status. */
function find_nav_groups(PDO $pdo): array
{
    $groups = [];
    foreach ($pdo->query('SELECT id, name, sort_order FROM nav_groups ORDER BY sort_order, id') as $g) {
        $groups[(int) $g['id']] = $g + ['items' => []];
    }
    foreach (find_nav_items($pdo) as $item) {
        $groups[(int) $item['group_id']]['items'][] = $item;
    }
    return array_values($groups);
}

function find_nav_items(PDO $pdo, ?int $id = null): array
{
    // siblings: the other entries that carry the same module grant — the module closes only
    // when every one of them is disabled.
    $st = $pdo->prepare(<<<'SQL'
        SELECT i.id, i.item_key, i.group_id, g.name AS group_name, i.sort_order, i.label, i.icon, i.url,
               i.opens, i.module, i.audience, i.status, i.is_locked, i.application_id,
               a.name AS application_name, COALESCE(a.is_builtin, true) AS is_builtin,
               (SELECT COALESCE(json_agg(json_build_object('label', s.label, 'status', s.status) ORDER BY s.id), '[]')
                  FROM nav_items s
                 WHERE s.module = i.module AND s.id <> i.id) AS siblings
          FROM nav_items i
          JOIN nav_groups g ON g.id = i.group_id
          LEFT JOIN applications a ON a.id = i.application_id
         WHERE CAST(:id AS bigint) IS NULL OR i.id = :id
         ORDER BY g.sort_order, g.id, i.sort_order, i.id
    SQL);
    $st->execute(['id' => $id]);
    return $st->fetchAll();
}

function find_nav_item(PDO $pdo, int $id): ?array
{
    return find_nav_items($pdo, $id)[0] ?? null;
}

function find_nav_group(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT g.id, g.name, g.sort_order,
                                (SELECT count(*) FROM nav_items i WHERE i.group_id = g.id) AS item_count
                           FROM nav_groups g WHERE g.id = :id');
    $st->execute(['id' => $id]);
    return $st->fetch() ?: null;
}

/**
 * The statuses this entry may take. A locked entry stays active. A part of the platform itself
 * that no module grant guards (Activity, Company, Departments) can leave the menu but cannot be
 * closed — there is no gate that a "disabled" could shut, and saying otherwise would be a lie.
 */
function nav_item_allowed_statuses(array $item): array
{
    if ($item['is_locked']) {
        return ['active'];
    }
    if ($item['module'] === null && $item['is_builtin']) {
        return ['active', 'hidden'];
    }
    return NAV_STATUSES;
}

/**
 * A link is an entry a super-admin added on the settings screen: it opens an address of their
 * choosing and belongs to no application. A built-in application's entry is the platform's own:
 * its address is the application's and it is never deleted (hide it instead) — an entry of an
 * external application, or a link, may be edited fully and removed. A locked entry stays.
 */
function nav_item_is_link(array $item): bool
{
    return $item['application_id'] === null;
}

function nav_item_address_editable(array $item): bool
{
    return nav_item_is_link($item) || !$item['is_builtin'];
}

function nav_item_deletable(array $item): bool
{
    return !$item['is_locked'] && nav_item_address_editable($item);
}

/** Save what a super-admin may change. Moving to another group puts the entry at its end. */
function update_nav_item(PDO $pdo, int $id, string $label, string $icon, int $groupId, string $status, string $url, string $opens): array
{
    $st = $pdo->prepare(<<<'SQL'
        UPDATE nav_items i
           SET label = :label, icon = :icon, status = :status, url = :url, opens = :opens,
               sort_order = CASE WHEN i.group_id = :g THEN i.sort_order
                                 ELSE (SELECT COALESCE(max(o.sort_order), 0) + 10 FROM nav_items o WHERE o.group_id = :g) END,
               group_id = :g
         WHERE i.id = :id
     RETURNING i.id, i.item_key, i.label, i.icon, i.group_id, i.status, i.url, i.opens
    SQL);
    $st->execute(['id' => $id, 'label' => $label, 'icon' => $icon, 'g' => $groupId, 'status' => $status, 'url' => $url, 'opens' => $opens]);
    return $st->fetch();
}

/**
 * Add a link at the end of its group. Its key is `link-<slug of the label>`, made unique with a
 * number — keys are immutable and load-bearing (nav-<key> DOM ids), so it is never the label.
 */
function insert_nav_item(PDO $pdo, int $groupId, string $label, string $icon, string $url, string $opens, string $status, int $memberId): array
{
    $slug = trim(preg_replace('/[^a-z0-9]+/', '-', strtolower($label)) ?? '', '-');
    $base = 'link-' . ($slug !== '' ? substr($slug, 0, 40) : 'entry');
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO nav_items (item_key, group_id, sort_order, label, icon, url, opens, status, created_by)
        SELECT :base || CASE WHEN n = 0 THEN '' ELSE '-' || n END, :g,
               (SELECT COALESCE(max(o.sort_order), 0) + 10 FROM nav_items o WHERE o.group_id = :g),
               :label, :icon, :url, :opens, :status, :member
          FROM generate_series(0, 999) AS n
         WHERE NOT EXISTS (SELECT 1 FROM nav_items k WHERE k.item_key = :base || CASE WHEN n = 0 THEN '' ELSE '-' || n END)
         ORDER BY n LIMIT 1
     RETURNING id, item_key, label, icon, group_id, status, url, opens
    SQL);
    $st->execute(['base' => $base, 'g' => $groupId, 'label' => $label, 'icon' => $icon, 'url' => $url,
                  'opens' => $opens, 'status' => $status, 'member' => $memberId]);
    return $st->fetch();
}

/** Remove an entry (member_nav_hidden rows go with it by cascade). The caller checks nav_item_deletable(). */
function delete_nav_item(PDO $pdo, int $id): bool
{
    $st = $pdo->prepare('DELETE FROM nav_items WHERE id = :id');
    $st->execute(['id' => $id]);
    return $st->rowCount() === 1;
}

/**
 * An address is a path of ours (`/reports/sales`) or a full web address (`https://…`) — never
 * javascript:, a bare host or a scheme we would not open. Null when it is fine.
 */
function nav_url_problem(string $url): ?string
{
    if ($url === '' || mb_strlen($url) > 2000) {
        return 'An entry needs an address: a path like /reports or a full address like https://example.com/.';
    }
    if (str_starts_with($url, '/')) {
        return str_starts_with($url, '//') ? 'A path starts with one slash.' : null;
    }
    if (preg_match('~^https?://[^\s/?#]+~i', $url) !== 1) {
        return 'A full address starts with http:// or https://.';
    }
    return null;
}

function set_nav_item_status(PDO $pdo, int $id, string $status): void
{
    $pdo->prepare('UPDATE nav_items SET status = :s WHERE id = :id')->execute(['s' => $status, 'id' => $id]);
}

/**
 * Move one place up or down among its neighbours: `nav_items` within their group, `nav_groups`
 * among themselves. The two trade sort_order. False at the edge. $table is never request input.
 */
function move_nav_row(PDO $pdo, string $table, int $id, string $direction): bool
{
    if (!in_array($table, ['nav_items', 'nav_groups'], true)) {
        throw new InvalidArgumentException('not a menu table');
    }
    $scope = $table === 'nav_items' ? 'AND n.group_id = r.group_id' : '';
    [$cmp, $order] = $direction === 'up' ? ['<', 'DESC'] : ['>', 'ASC'];
    $pdo->beginTransaction();
    try {
        $st = $pdo->prepare("SELECT n.id, n.sort_order, r.sort_order AS mine
                               FROM $table r JOIN $table n ON (n.sort_order, n.id) $cmp (r.sort_order, r.id) $scope
                              WHERE r.id = :id
                              ORDER BY n.sort_order $order, n.id $order LIMIT 1 FOR UPDATE OF n, r");
        $st->execute(['id' => $id]);
        $neighbour = $st->fetch();
        if ($neighbour === false) {
            $pdo->rollBack();
            return false;
        }
        // Equal sort_orders (a hand-made row) would make the trade a no-op: step past instead.
        $mine = (int) $neighbour['mine'];
        $theirs = (int) $neighbour['sort_order'];
        if ($mine === $theirs) {
            $theirs += $direction === 'up' ? -1 : 1;
        }
        $set = $pdo->prepare("UPDATE $table SET sort_order = :s WHERE id = :id");
        $set->execute(['s' => $theirs, 'id' => $id]);
        $set->execute(['s' => $mine, 'id' => (int) $neighbour['id']]);
        $pdo->commit();
        return true;
    } catch (Throwable $ex) {
        $pdo->rollBack();
        throw $ex;
    }
}

/** A new group goes last. */
function upsert_nav_group(PDO $pdo, ?int $id, string $name): array
{
    if ($id === null) {
        $st = $pdo->prepare('INSERT INTO nav_groups (name, sort_order)
                             VALUES (:n, (SELECT COALESCE(max(sort_order), 0) + 10 FROM nav_groups))
                             RETURNING id, name');
        $st->execute(['n' => $name]);
    } else {
        $st = $pdo->prepare('UPDATE nav_groups SET name = :n WHERE id = :id RETURNING id, name');
        $st->execute(['n' => $name, 'id' => $id]);
    }
    return $st->fetch();
}

/** Only an empty group can go (the FK is ON DELETE RESTRICT; this is the polite refusal). */
function delete_nav_group(PDO $pdo, int $id): bool
{
    $st = $pdo->prepare('DELETE FROM nav_groups g WHERE g.id = :id
                            AND NOT EXISTS (SELECT 1 FROM nav_items i WHERE i.group_id = g.id)');
    $st->execute(['id' => $id]);
    return $st->rowCount() === 1;
}
