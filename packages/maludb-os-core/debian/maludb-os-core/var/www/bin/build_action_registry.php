<?php
declare(strict_types=1);

/**
 * Build mcp/action_registry.json from docs/business-os-action-manifest.md.
 *
 * The manifest is the contract between the voice surface and the app: every screen the
 * assistant can reach and every action it can perform. This script turns it into the
 * registry the actions MCP server loads at startup, so the tool list and the document can
 * never drift — a screen or action missing from the manifest is unreachable by voice, and
 * one added to the manifest is reachable as soon as its endpoint exists.
 *
 * It never guesses. An endpoint it cannot resolve, or a params cell it cannot parse, is
 * reported and marked unresolved rather than approximated.
 *
 *   php bin/build_action_registry.php            # write the registry, print a summary
 *   php bin/build_action_registry.php --check    # verify only; non-zero exit if stale
 */

const MANIFEST = __DIR__ . '/../docs/business-os-action-manifest.md';
const REGISTRY = __DIR__ . '/../mcp/action_registry.json';
const WEB_ROOT = __DIR__ . '/../html';

$checkOnly = in_array('--check', $argv, true);

$lines = file(MANIFEST, FILE_IGNORE_NEW_LINES);
if ($lines === false) {
    fwrite(STDERR, "Cannot read the manifest.\n");
    exit(1);
}

$screens = [];
$actions = [];
$problems = [];

$section = '';
$sectionBases = [];
$mode = '';                     // 'screens' | 'actions' | ''

foreach ($lines as $no => $line) {
    $lineNo = $no + 1;

    if (str_starts_with($line, '## ')) {
        $section = trim(substr($line, 3));
        $sectionBases = [];
        $mode = '';
        continue;
    }
    if (preg_match('/^Screens:/', $line)) {
        $mode = 'screens';
        continue;
    }
    if (preg_match('/^Actions\b(.*)$/', $line, $m)) {
        $mode = 'actions';
        // "Actions (base `/contacts/`, deals under `/deals/`)" — collect every path it names.
        preg_match_all('/`(\/[^`]*)`/', $m[1], $bases);
        $sectionBases = $bases[1] ?? [];
        continue;
    }
    if ($line === '' || $line[0] !== '|') {
        continue;
    }

    $cells = array_map('trim', explode('|', trim($line, "| \t")));
    if ($cells === [] || str_starts_with($cells[0], '---') || $cells[0] === 'Screen id' || $cells[0] === 'Action'
        || $cells[0] === 'Tool' || $cells[0] === 'Work item' || $cells[0] === '#') {
        continue;
    }

    if ($mode === 'screens' && count($cells) >= 3) {
        $id = trim($cells[0], '`');
        if (!preg_match('/^[a-z0-9-]+$/', $id)) {
            continue;                                   // not a screen row (a prose table)
        }
        $url = trim($cells[1], '`');
        [$description, $params] = split_screen_description($cells[2]);
        $controller = screen_controller($url);
        $screens[$id] = [
            'screen' => $id,
            'url' => $url,
            'section' => $section,
            'when' => $description,
            'params' => $params,
            'built' => $controller !== null && !is_stub($controller),
            'stub' => $controller !== null && is_stub($controller),
        ];
        continue;
    }

    if ($mode === 'actions' && count($cells) >= 8) {
        $name = trim($cells[0], '`');
        if (!preg_match('/^[a-z0-9_]+$/', $name)) {
            continue;
        }
        $file = trim($cells[1], '`');
        $endpoint = resolve_endpoint($file, $sectionBases);
        if ($endpoint === null) {
            $problems[] = "line {$lineNo}: {$name} — cannot resolve endpoint '{$file}'"
                . ($sectionBases === [] ? ' (the section names no base path)'
                                        : ' among bases ' . implode(', ', $sectionBases));
        }
        $actions[$name] = [
            'action' => $name,
            'section' => $section,
            'endpoint' => $endpoint,
            'params' => parse_params($cells[2]),
            'undo' => $cells[3] === '—' ? null : $cells[3],
            'confirm' => str_contains($cells[4], '✔'),
            'approval' => $cells[5] === '' ? null : $cells[5],
            'log_event' => trim($cells[6], '`'),
            'who' => $cells[7],
            'built' => $endpoint !== null && is_file(WEB_ROOT . $endpoint),
        ];
    }
}

/*
 * "**organization**, any field of organization_create" — the manifest's way of saying an update
 * takes the record and whichever fields change. parse_params() keeps that phrase as a note; here
 * it becomes what it means: the named action's fields, every one optional, and the action marked
 * `partial` so the tool tells PHP to keep what it was not sent (app/partial_update.php).
 * Found by the 2026-09-19 action smoke: without this the ten update tools took a record and
 * nothing else, and every save handler refused the empty form.
 */
foreach ($actions as $name => $action) {
    foreach ($action['params'] as $i => $p) {
        if (($p['name'] ?? null) !== null || !preg_match('/^any field of ([a-z0-9_]+)$/', (string) ($p['note'] ?? ''), $m)) {
            continue;
        }
        $source = $actions[$m[1]] ?? null;
        if ($source === null) {
            $problems[] = "{$name}: 'any field of {$m[1]}' names no action";
            continue;
        }
        $have = array_column(array_filter($action['params'], static fn (array $q): bool => ($q['name'] ?? null) !== null), 'name');
        $extra = [];
        foreach ($source['params'] as $q) {
            if (($q['name'] ?? null) !== null && !in_array($q['name'], $have, true)) {
                $extra[] = ['required' => false] + $q;
            }
        }
        array_splice($actions[$name]['params'], $i, 1, $extra);
        $actions[$name]['partial'] = true;
    }
}

/** "to browse quotes (params: `status`, `organization`)" → description + param names. */
function split_screen_description(string $cell): array
{
    $params = [];
    if (preg_match('/\(params:\s*(.+?)\)\s*$/', $cell, $m)) {
        preg_match_all('/`([a-z0-9_]+)`/', $m[1], $found);
        $params = $found[1] ?? [];
        $cell = trim(preg_replace('/\(params:.*?\)\s*$/', '', $cell));
    }
    return [trim($cell), $params];
}

/** True when the controller is a module placeholder rather than the real screen. */
function is_stub(string $controllerPath): bool
{
    $source = @file_get_contents($controllerPath);
    return $source !== false && str_contains($source, 'render_module_stub(');
}

/** The controller answering a screen's canonical URL, or null when nothing does. */
function screen_controller(string $url): ?string
{
    $path = parse_url($url, PHP_URL_PATH) ?: $url;
    $path = '/' . ltrim($path, '/');
    $path = preg_replace('/\{[a-z_]+\}/', '1', $path);          // /invoices/{id} → /invoices/1

    if (str_ends_with($path, '/')) {
        return is_file(WEB_ROOT . $path . 'index.php') ? WEB_ROOT . $path . 'index.php' : null;
    }
    if (is_file(WEB_ROOT . $path . '.php')) {
        return WEB_ROOT . $path . '.php';                       // /my-work → my-work.php
    }
    if (is_file(WEB_ROOT . $path . '/index.php')) {
        return WEB_ROOT . $path . '/index.php';                 // /team/departments → …/index.php
    }
    // The canonical-URL rewrites: /{module}/new → form.php, /{module}/{id} → view.php.
    $parts = explode('/', trim($path, '/'));
    $last = array_pop($parts);
    $dir = '/' . implode('/', $parts);
    if ($last === 'new') {
        return is_file(WEB_ROOT . $dir . '/form.php') ? WEB_ROOT . $dir . '/form.php' : null;
    }
    if ($last === 'edit') {
        array_pop($parts);                                      // drop the {id} segment
        $form = WEB_ROOT . '/' . implode('/', $parts) . '/form.php';
        return is_file($form) ? $form : null;
    }
    if (ctype_digit($last)) {
        return is_file(WEB_ROOT . $dir . '/view.php') ? WEB_ROOT . $dir . '/view.php' : null;
    }
    return null;
}

/** Absolute file → itself; otherwise the one section base that yields an existing file. */
function resolve_endpoint(string $file, array $bases): ?string
{
    if ($file === '' || $file === '—') {
        return null;
    }
    if (str_starts_with($file, '/')) {
        return $file;
    }
    if (count($bases) === 1) {
        return rtrim($bases[0], '/') . '/' . ltrim($file, '/');
    }
    $hits = [];
    foreach ($bases as $base) {
        $candidate = rtrim($base, '/') . '/' . ltrim($file, '/');
        if (is_file(WEB_ROOT . $candidate)) {
            $hits[] = $candidate;
        }
    }
    return count($hits) === 1 ? $hits[0] : null;                // ambiguous → unresolved
}

/**
 * "**name**, relationship_types[], email" → typed param list. Bold is required, a `[]`
 * suffix is a repeated field, and anything in parentheses is a hint for the tool description.
 */
function parse_params(string $cell): array
{
    $params = [];
    foreach (explode(',', $cell) as $piece) {
        $piece = trim($piece);
        if ($piece === '' || $piece === '—') {
            continue;
        }
        $required = str_contains($piece, '**');
        $hint = '';
        if (preg_match('/\((.+?)\)/', $piece, $m)) {
            $hint = trim($m[1]);
            $piece = trim(preg_replace('/\(.+?\)/', '', $piece));
        }
        $piece = trim(str_replace(['**', '`'], '', $piece));

        // "any field of deal_create" and "organization_id or contact_id or deal_id" are
        // prose, not a field: keep them as guidance on the tool, not as a schema field.
        if (str_contains($piece, ' or ')) {
            foreach (explode(' or ', $piece) as $alternative) {
                $alternative = trim($alternative);
                if (preg_match('/^[a-z0-9_]+(\[\])?$/', $alternative)) {
                    $params[] = param($alternative, false, 'one of these is required');
                }
            }
            continue;
        }
        if (!preg_match('/^[a-z0-9_]+(\[\])?$/', $piece)) {
            $params[] = ['name' => null, 'note' => $piece];
            continue;
        }
        $params[] = param($piece, $required, $hint);
    }
    return $params;
}

function param(string $piece, bool $required, string $hint): array
{
    $isArray = str_ends_with($piece, '[]');
    $name = $isArray ? substr($piece, 0, -2) : $piece;
    return ['name' => $name, 'required' => $required, 'repeated' => $isArray, 'hint' => $hint];
}

$registry = [
    'generated_from' => 'docs/business-os-action-manifest.md',
    'generated_at' => date('c'),
    'screens' => $screens,
    'actions' => $actions,
];
$json = json_encode($registry, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n";

$builtScreens = count(array_filter($screens, static fn ($s) => $s['built']));
$builtActions = count(array_filter($actions, static fn ($a) => $a['built']));

if ($checkOnly) {
    $current = is_file(REGISTRY) ? file_get_contents(REGISTRY) : '';
    $stale = preg_replace('/"generated_at": "[^"]*",\n/', '', $current)
          !== preg_replace('/"generated_at": "[^"]*",\n/', '', $json);
    echo $stale ? "STALE: the registry does not match the manifest. Run bin/build_action_registry.php\n"
                : "OK: registry matches the manifest.\n";
    exit($stale ? 1 : 0);
}

file_put_contents(REGISTRY, $json);

printf("%d screens (%d built), %d actions (%d built) → mcp/action_registry.json\n",
    count($screens), $builtScreens, count($actions), $builtActions);
foreach ($problems as $problem) {
    fwrite(STDERR, "  unresolved: {$problem}\n");
}
if ($problems !== []) {
    fwrite(STDERR, sprintf("  %d unresolved endpoint(s) — registered but never exposed as tools.\n", count($problems)));
}
