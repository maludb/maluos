<?php
declare(strict_types=1);

/**
 * Partial updates for the agents' door (found by the action smoke, 2026-09-19).
 *
 * A save handler reads a whole form: a field that is missing means "the person cleared it". That
 * is right for a browser, which always sends the whole form, and wrong for an `*_update` action
 * tool, which sends the record and only what changes — the handler refused the rest as blank
 * ("A company needs a name"), or would have wiped it.
 *
 * So when — and only when — the request is authenticated by an action token and carries
 * `_partial=1`, the fields it did NOT send are filled in from the record's own row before the
 * handler runs. Two rules make that safe:
 *
 *  - The row is read from the BASE TABLE, never from an `mcp_*` view: the views hide columns
 *    (an organisation's tax_id, a deal's probability override), and refilling a form from a view
 *    is how those get wiped — the bug class this project has already found twice.
 *  - Nothing is filled unless the caller can see the record through its `mcp_*` view. The
 *    handler makes its own check afterwards and still decides; this only declines to load a row
 *    on behalf of someone who could not have opened it.
 *
 * No handler is edited, and a browser can never trigger this: a session request is not
 * action-authenticated, so `_partial` from a form is ignored.
 */

/** endpoint → [table, the form's id field, read view, the view's id column] */
const PARTIAL_UPDATE_TARGETS = [
    '/interactions/save.php'           => ['interactions', 'interaction', 'mcp_interactions', 'interaction_id'],
    '/quotes/save.php'                 => ['quotes', 'quote', 'mcp_quotes', 'quote_id'],
    '/time/save.php'                   => ['time_entries', 'time_entry', 'mcp_time_entries', 'time_entry_id'],
    '/content/campaigns/save.php'      => ['campaigns', 'campaign', 'mcp_campaigns', 'campaign_id'],
];

function partial_update_prefill(PDO $pdo): void
{
    if (empty($GLOBALS['__action_authed']) || ($_POST['_partial'] ?? '') !== '1'
        || ($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
        return;
    }
    unset($_POST['_partial']);
    $target = PARTIAL_UPDATE_TARGETS[(string) parse_url((string) ($_SERVER['SCRIPT_NAME'] ?? ''), PHP_URL_PATH)] ?? null;
    if ($target === null) {
        return;
    }
    [$table, $idField, $view, $viewId] = $target;
    $id = filter_var($_POST[$idField] ?? null, FILTER_VALIDATE_INT);
    if ($id === false || $id === null || $id < 1) {
        return;
    }

    $visible = $pdo->prepare("SELECT 1 FROM {$view} WHERE {$viewId} = :id");
    $visible->execute(['id' => $id]);
    if ($visible->fetchColumn() === false) {
        return;
    }
    $st = $pdo->prepare("SELECT * FROM {$table} WHERE id = :id");
    $st->execute(['id' => $id]);
    $row = $st->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return;
    }

    // A tool sends a list as one comma-separated string; a form sends an array.
    if (isset($_POST['relationship_types']) && is_string($_POST['relationship_types'])) {
        $_POST['relationship_types'] = array_values(array_filter(array_map('trim', explode(',', $_POST['relationship_types']))));
    }

    foreach ($row as $column => $value) {
        if ($column === 'id' || $value === null) {
            continue;
        }
        if ($column === 'address') {
            // jsonb {line1, line2, city, region, postal, country} ↔ the form's address_* fields.
            $address = is_string($value) ? (json_decode($value, true) ?: []) : (array) $value;
            foreach ($address as $key => $part) {
                $_POST['address_' . $key] ??= (string) $part;
            }
            continue;
        }
        if (array_key_exists($column, $_POST)) {
            continue;
        }
        if (is_bool($value)) {
            // Said outright, both ways: request_bool('x') reads '0' as false exactly as it reads an
            // absent checkbox, and a handler that treats "not sent" as a default (Time's billable)
            // must not mistake a stored false for "not sent".
            $_POST[$column] = $value ? '1' : '0';
            continue;
        }
        if (is_string($value) && str_starts_with($value, '{') && str_ends_with($value, '}') && $column === 'relationship_types') {
            $_POST[$column] = array_values(array_filter(array_map(
                static fn (string $v): string => trim($v, '"'), explode(',', trim($value, '{}')))));
            continue;
        }
        $_POST[$column] = (string) $value;
    }
}
