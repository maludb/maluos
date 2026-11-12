<?php
declare(strict_types=1);

/**
 * An application on a server of its own (MaluOS Phase 14 slice 3; db/194; maluos docs/phase14-application-servers.md).
 *
 * bin/app_install.php runs in two halves there. The HOST half runs on the application server (the code, the
 * database, config/.env, the vhost, the units) and asks the kernel for the rest through three calls under its
 * node token, served on the applications' door only:
 *
 *   POST /api/v1/estate/apps/prepare   what the host half needs from the kernel before it starts
 *   POST /api/v1/estate/apps/register  the bundle (the manifest, the action registry, the skills, the agents' job
 *                                      descriptions) and the host's report; the kernel runs the KERNEL half on it
 *                                      in the background (registration, roles, the registry, grants, the hires)
 *   GET  /api/v1/estate/apps/job?id=   that run's state, its output, and once the application token
 *
 * A node may ask only for the applications its join code named (locations.node_apps).
 */

const APP_BUNDLE_MAX_BYTES = 8 * 1024 * 1024;
const APP_BUNDLE_MAX_FILES = 400;

/** Where registrations are staged: under the tenant's storage root, never under a web root. */
function app_install_staging_root(): string
{
    $root = rtrim((string) (env('STORAGE_ROOT') ?: (APP_ROOT . '/storage')), '/') . '/app-installs';
    if (!is_dir($root)) { @mkdir($root, 0750, true); }
    return $root;
}

/** The node's allowance as a list of catalog keys. */
function app_install_node_apps(array $node): array
{
    $raw = trim((string) ($node['node_apps'] ?? '{}'), '{}');
    return $raw === '' ? [] : array_values(array_filter(array_map(static fn (string $k): string => trim($k, '" '), explode(',', $raw))));
}

/** A bundle path the kernel half may read: relative, plain, no dot segment, no dot file. */
function app_bundle_path_ok(string $p): bool
{
    return preg_match('#^[A-Za-z0-9_][A-Za-z0-9_.@ -]*(/[A-Za-z0-9_][A-Za-z0-9_.@ -]*){0,7}$#', $p) === 1 && !str_contains($p, '..') && strlen($p) <= 200;
}

/**
 * Write the bundle {path: base64} into a fresh staging directory for this node and key. Answers [dir, error].
 * @param array<string,string> $files
 */
function app_bundle_stage(int $nodeId, string $key, array $files): array
{
    if (count($files) === 0 || count($files) > APP_BUNDLE_MAX_FILES) { return [null, 'the bundle carries no file, or more than ' . APP_BUNDLE_MAX_FILES]; }
    if (!isset($files['maludb-os.json'])) { return [null, 'the bundle has no maludb-os.json']; }
    $dir = app_install_staging_root() . '/' . $nodeId . '-' . $key . '-' . gmdate('Ymd\THis') . '-' . bin2hex(random_bytes(4));
    if (!@mkdir($dir, 0750, true)) { return [null, 'the staging directory could not be made']; }
    $total = 0;
    foreach ($files as $path => $b64) {
        if (!is_string($path) || !is_string($b64) || !app_bundle_path_ok($path)) { return [null, 'a bundle path is not acceptable: ' . json_encode($path)]; }
        $data = base64_decode($b64, true);
        if ($data === false) { return [null, "{$path} is not base64"]; }
        $total += strlen($data);
        if ($total > APP_BUNDLE_MAX_BYTES) { return [null, 'the bundle is larger than ' . intdiv(APP_BUNDLE_MAX_BYTES, 1024 * 1024) . ' MB']; }
        $target = $dir . '/' . $path;
        if (!is_dir(dirname($target))) { @mkdir(dirname($target), 0750, true); }
        if (@file_put_contents($target, $data) === false) { return [null, "{$path} could not be staged"]; }
    }
    return [$dir, null];
}

/** The job id is the staging directory's name; a node reads only its own. */
function app_install_job_dir(int $nodeId, string $id): ?string
{
    if (preg_match('/^' . $nodeId . '-[a-z][a-z0-9_]{1,31}-[0-9T]{15}-[0-9a-f]{8}$/', $id) !== 1) { return null; }
    $dir = app_install_staging_root() . '/' . $id;
    return is_dir($dir) ? $dir : null;
}

/** Start the kernel half on a staged bundle, detached; its output and exit code land in the staging directory. */
function app_install_start(string $dir, array $args): void
{
    $cmd = 'php ' . escapeshellarg(APP_ROOT . '/bin/app_install.php') . ' apply ' . escapeshellarg($dir) . ' --half kernel';
    foreach ($args as $k => $v) {
        if ($v === false || $v === null || $v === '') { continue; }
        $cmd .= ' --' . $k . ($v === true ? '' : ' ' . escapeshellarg((string) $v));
    }
    $sh = 'cd ' . escapeshellarg(APP_ROOT) . ' && ' . $cmd . ' > ' . escapeshellarg($dir . '/log.txt') . ' 2>&1; echo $? > ' . escapeshellarg($dir . '/exit');
    exec('nohup setsid sh -c ' . escapeshellarg($sh) . ' > /dev/null 2>&1 &');
}

/** The job as the host half reads it. The application token is answered once and removed. */
function app_install_job(string $dir): array
{
    $exit = is_file($dir . '/exit') ? trim((string) file_get_contents($dir . '/exit')) : null;
    $log = is_file($dir . '/log.txt') ? (string) file_get_contents($dir . '/log.txt') : '';
    $out = ['state' => $exit === null ? 'running' : ($exit === '0' ? 'done' : 'failed'), 'exit' => $exit === null ? null : (int) $exit,
            'output' => strlen($log) > 60000 ? substr($log, -60000) : $log];
    if ($exit !== null && is_file($dir . '/result.json')) {
        $out['result'] = json_decode((string) file_get_contents($dir . '/result.json'), true) ?: [];
        @unlink($dir . '/result.json');
    }
    return $out;
}

/** The scheme the kernel is served under (APP_URL), for an application registered from another server. */
function app_install_scheme(): string
{
    return str_starts_with((string) env('APP_URL', ''), 'https://') ? 'https' : 'http';
}
