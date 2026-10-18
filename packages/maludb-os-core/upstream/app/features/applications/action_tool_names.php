<?php
declare(strict_types=1);

/**
 * K55 (2026-10-11; spec docs/build-specs/kernel-action-tool-names.md): one name per action on the kernel's ONE Actions MCP.
 *
 * Every application's built actions become tools on the same server (mcp/application_actions.py), under one flat list of
 * names. Until this file a name two applications both used — or an application and the kernel — was registered for whichever
 * registry file sorted first and silently skipped for the rest, and an agent granted that name was handed the other
 * application's tool. Each built action now carries a `tool_name` in its registry file (mcp/registries/<app_key>.json):
 *
 *   - its own action name, when no other registry has a built action of that name and the kernel has no action of that name;
 *   - otherwise "<app_key>_<action>".
 *
 * A tool name once given is KEPT while it is still free: an application installed later that shares a name takes the prefix,
 * and the application that had the name keeps it — so installing an application never renames another's tools or breaks its
 * agents' grants. bin/actions_tool_names.php gives today's registries their names once and moves the grants; the installer's
 * registry step (bin/app_install.php, step 11) and the hire script use the same functions from then on.
 */

/** The longest tool name a model API accepts. */
const ACTION_TOOL_NAME_MAX = 64;

/** The kernel's own built action names (mcp/action_registry.json): they keep their names, and an application's action of the
 *  same name takes the prefix. */
function kernel_action_names(string $kernelDir): array
{
    $file = $kernelDir . '/mcp/action_registry.json';
    $reg = is_file($file) ? (json_decode((string) file_get_contents($file), true) ?: []) : [];
    $names = [];
    foreach ((array) ($reg['actions'] ?? []) as $a) {
        if (is_array($a) && !empty($a['built']) && isset($a['action'])) { $names[(string) $a['action']] = true; }
    }
    return $names;
}

/** Every registry file, app_key => the decoded file, in file-name order (the server's order). Unreadable files are left out. */
function load_action_registries(string $dir): array
{
    $out = [];
    $files = glob(rtrim($dir, '/') . '/*.json') ?: [];
    sort($files, SORT_STRING);
    foreach ($files as $f) {
        $reg = json_decode((string) file_get_contents($f), true);
        if (!is_array($reg) || !is_string($reg['app_key'] ?? null) || !is_array($reg['registry']['actions'] ?? null)) { continue; }
        $out[$reg['app_key']] = $reg;
    }
    return $out;
}

/** The name a built action is served under. */
function action_tool_name(array $action): string
{
    return (string) (($action['tool_name'] ?? '') !== '' ? $action['tool_name'] : $action['action']);
}

/** A registry file's built actions: action key => the action. */
function registry_built_actions(array $file): array
{
    return array_filter((array) ($file['registry']['actions'] ?? []), static fn ($a): bool => is_array($a) && !empty($a['built']) && isset($a['action']));
}

/**
 * Give every built action of `$file` — the registry about to be written for `$key` — its tool_name. `$previous` is the file it
 * replaces (null for a first install); `$others` every other application's registry file (app_key => file); `$kernelNames`
 * kernel_action_names(). Answers [the file with tool_name set on its built actions, [the actions it could not name => why]].
 */
function assign_registry_tool_names(string $key, array $file, ?array $previous, array $others, array $kernelNames): array
{
    $sharedBare = $kernelNames;                // a name the kernel or another application also uses → the prefix
    $takenTools = $kernelNames;                // the names already served by someone else
    foreach ($others as $otherKey => $other) {
        if ($otherKey === $key) { continue; }
        foreach (registry_built_actions($other) as $a) {
            $sharedBare[(string) $a['action']] = true;
            $takenTools[action_tool_name($a)] = true;
        }
    }
    $before = [];
    foreach (registry_built_actions($previous ?? []) as $actionKey => $a) {
        if (($a['tool_name'] ?? '') !== '') { $before[(string) $actionKey] = (string) $a['tool_name']; }
    }
    $clashes = [];
    $mine = [];
    foreach ((array) ($file['registry']['actions'] ?? []) as $actionKey => $a) {
        if (!is_array($a) || empty($a['built']) || !isset($a['action'])) { continue; }
        $name = (string) $a['action'];
        $kept = $before[(string) $actionKey] ?? null;
        if ($kept !== null && !isset($takenTools[$kept]) && !isset($mine[$kept])) {
            $tool = $kept;
        } elseif (!isset($sharedBare[$name]) && !isset($mine[$name])) {
            $tool = $name;
        } else {
            $tool = $key . '_' . $name;
        }
        if (isset($takenTools[$tool]) || isset($mine[$tool])) {
            $clashes[$name] = "'{$tool}' is already another tool's name";
            unset($file['registry']['actions'][$actionKey]['tool_name']);
            continue;
        }
        if (strlen($tool) > ACTION_TOOL_NAME_MAX || !preg_match('/^[a-zA-Z0-9_-]+$/', $tool)) {
            $clashes[$name] = "'{$tool}' is not a usable tool name (letters, digits, _ and -, at most " . ACTION_TOOL_NAME_MAX . ')';
            unset($file['registry']['actions'][$actionKey]['tool_name']);
            continue;
        }
        $mine[$tool] = true;
        $file['registry']['actions'][$actionKey]['tool_name'] = $tool;
    }
    return [$file, $clashes];
}

/**
 * Every registry at once (bin/actions_tool_names.php): each in turn, against the others as they stand after the ones before
 * it. Today's sharers all take the prefix (none has a kept name yet); a name already given is kept. Answers
 * [app_key => the file with tool names, app_key => [action => why it could not be named]].
 */
function assign_all_tool_names(array $registries, array $kernelNames): array
{
    $out = $registries;
    $clashes = [];
    foreach (array_keys($out) as $key) {
        [$out[$key], $c] = assign_registry_tool_names($key, $out[$key], $registries[$key], $out, $kernelNames);
        if ($c !== []) { $clashes[$key] = $c; }
    }
    return [$out, $clashes];
}

/** For the hire script: a declared action name of `$key` → the tool it is served under (the name itself when the application
 *  has no registry here yet, or the action is not built). */
function application_action_tool_map(string $kernelDir, string $key): array
{
    $file = $kernelDir . '/mcp/registries/' . $key . '.json';
    $reg = is_file($file) ? (json_decode((string) file_get_contents($file), true) ?: []) : [];
    $map = [];
    foreach (registry_built_actions($reg) as $a) { $map[(string) $a['action']] = action_tool_name($a); }
    return $map;
}
