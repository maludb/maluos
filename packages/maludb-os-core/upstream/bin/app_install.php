<?php
declare(strict_types=1);
/**
 * The installer for an application from us (build plan C4 / Projects' K3, 2026-09-28): the deterministic
 * script the `os-install` skill drives, and the step the provisioning script runs for the default
 * applications (K4). Every step of the plugin's runbook, in its order, each idempotent — a step that finds
 * its work done says so and moves on — so the same command installs fresh, finishes a half-done install,
 * and reconciles a hand-made one. Nothing is improvised: the manifest (maludb-os.json) says what, the
 * kernel's own functions do the registration as the super-admin named, and every kernel write is logged.
 *
 *   php bin/app_install.php plan  <repository dir or git URL> [options]     read-only: what is done, what would be done
 *   sudo php bin/app_install.php apply <repository dir or git URL> [options]  root: does what is not yet done, in order
 *
 * Options: --by <super-admin email> (default: the first super-admin)   --domain <business domain> (default: from APP_HOST)
 *          --scheme http|https (default: http — the owner's proxy terminates TLS)   --tenant <db prefix> (default: the
 *          domain's first label)   --ref <git tag or commit> (when cloning)   --hire-agents (hire every agents[] entry — the
 *          default applications' rule; otherwise they are proposed)   --grant-standing-departments (every standing
 *          department gets the application's member role at write — K4)   --no-restart (never restart maludb-os-actions-mcp)
 *
 * What stays the owner's: DNS for <label>.<domain>, TLS, and any grant not named here. A name that does not resolve
 * yet gets a loopback line in /etc/hosts, and the plan says so.
 *
 * deploy/ files are templates: {{DOMAIN}}, {{APP_DIR}}, {{APP_KEY}} and any env key ({{APP_INTERNAL_PORT}},
 * {{MCP_RECORDS_PORT}} …) are filled in; a file with no placeholders is installed as it is, with a note.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
$KERNEL = dirname(__DIR__);
require_once $KERNEL . '/app/bootstrap.php';
require_once $KERNEL . '/app/features/applications/render.php';
require_once $KERNEL . '/app/features/applications/sso.php';
require_once $KERNEL . '/app/features/skills/import.php';
require_once $KERNEL . '/app/features/skills/queries.php';
applications_require_files();

// ---- arguments -------------------------------------------------------------------------------------------------
$argvAll = $GLOBALS['argv'];
$mode = $argvAll[1] ?? '';
$source = $argvAll[2] ?? '';
$opts = [];
for ($i = 3, $n = count($argvAll); $i < $n; $i++) {
    if (!str_starts_with($argvAll[$i], '--')) { continue; }
    $k = substr($argvAll[$i], 2);
    if (str_contains($k, '=')) { [$k, $v] = explode('=', $k, 2); $opts[$k] = $v; continue; }
    $opts[$k] = isset($argvAll[$i + 1]) && !str_starts_with($argvAll[$i + 1], '--') ? $argvAll[++$i] : true;
}
if (!in_array($mode, ['plan', 'apply'], true) || $source === '') {
    fwrite(STDERR, "Usage: php bin/app_install.php plan|apply <repository dir or git URL> [--by <email>] [--domain <domain>] [--scheme http|https]\n"
        . "       [--tenant <db prefix>] [--ref <tag>] [--hire-agents] [--grant-standing-departments] [--no-restart] [--rotate-db-passwords]\n");
    exit(1);
}
$APPLY = $mode === 'apply';
if ($APPLY && posix_geteuid() !== 0) {
    fwrite(STDERR, "apply writes /etc, /srv/apps and the database roles — run it as root: sudo php bin/app_install.php apply …\n");
    exit(1);
}

// ---- helpers ---------------------------------------------------------------------------------------------------
$report = [];
function say(string $step, string $state, string $detail): void
{
    global $report;
    $report[] = [$step, $state, $detail];
    printf("%-7s %-24s %s\n", $state, $step, $detail);
}
function stop(string $step, string $why): never
{
    say($step, 'STOP', $why);
    fwrite(STDERR, "\nStopped at {$step}: {$why}\n");
    exit(2);
}
/** Run a shell command (apply only); answers [exit code, output]. In plan mode it is printed and not run. */
function sh(string $cmd, bool $quiet = false): array
{
    global $APPLY;
    if (!$APPLY) {
        if (!$quiet) { echo "        \$ {$cmd}\n"; }
        return [0, ''];
    }
    exec($cmd . ' 2>&1', $out, $code);
    return [$code, implode("\n", $out)];
}
/** A read-only shell query, run in both modes. */
function q(string $cmd): array
{
    exec($cmd . ' 2>&1', $out, $code);
    return [$code, implode("\n", $out)];
}
function psql(string $sql, string $db = 'postgres'): array
{
    return q('runuser -u postgres -- psql -At -v ON_ERROR_STOP=1 -d ' . escapeshellarg($db) . ' -c ' . escapeshellarg($sql));
}
function psql_ro(string $sql, string $db = 'postgres'): array
{
    $pre = posix_geteuid() === 0 ? 'runuser -u postgres --' : 'sudo -n -u postgres';
    return q($pre . ' psql -At -d ' . escapeshellarg($db) . ' -c ' . escapeshellarg($sql));
}
function env_file_read(string $path): array
{
    $out = [];
    if (!is_readable($path)) { return $out; }
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (preg_match('/^([A-Z][A-Z0-9_]*)=(.*)$/', $line, $m)) { $out[$m[1]] = trim($m[2], '"'); }
    }
    return $out;
}
function env_quote(string $v): string
{
    return preg_match('/[\s#"\']/', $v) ? '"' . str_replace('"', '\"', $v) . '"' : $v;
}
/** K=V into the text of an env file: in place when the key is already there (set or empty), else appended. */
function env_lines_set(string $lines, string $k, string $v): string
{
    $line = $k . '=' . env_quote($v);
    $n = 0;
    $out = (string) preg_replace_callback('/^' . preg_quote($k, '/') . '=.*$/m', static fn (): string => $line, $lines, 1, $n);
    if ($n > 0) { return $out; }
    return ($lines === '' ? '' : rtrim($lines) . "\n") . $line . "\n";
}
/**
 * The business's MaluMail sending key and sender, for an application's config/.env. The key comes from `~/.malumail` of the
 * person installing — the sudo user's home, then $HOME, then the kernel directory's owner's home; the file is one line (the key)
 * or env-style lines (MALUMAIL_API_KEY, MAIL_FROM, MAIL_FROM_NAME) — else from the kernel's own config/.env. The sender
 * (MAIL_FROM, MAIL_FROM_NAME) comes from the same file, else the kernel's config/.env, else is left empty for the caller's
 * default. Answers the three keys ('' when unknown) and `source`, a path or phrase for the report — the key itself is never printed.
 */
function malumail_values(array $kernelEnv, string $kernelDir): array
{
    $homes = [];
    $su = (string) getenv('SUDO_USER');
    if ($su !== '' && ($pw = @posix_getpwnam($su)) && !empty($pw['dir'])) { $homes[] = (string) $pw['dir']; }
    if (($h = (string) getenv('HOME')) !== '') { $homes[] = $h; }
    if (($uid = @fileowner($kernelDir)) !== false && ($pw = @posix_getpwuid((int) $uid)) && !empty($pw['dir'])) { $homes[] = (string) $pw['dir']; }
    $found = [];
    $source = '';
    foreach (array_unique($homes) as $home) {
        $path = rtrim($home, '/') . '/.malumail';
        if (!is_readable($path)) { continue; }
        $text = trim((string) file_get_contents($path));
        if ($text === '') { continue; }
        if (preg_match('/^[A-Z][A-Z0-9_]*=/m', $text)) {
            $found = env_file_read($path);
        } else {
            foreach (preg_split('/\R/', $text) ?: [] as $line) {
                $line = trim($line);
                if ($line !== '' && $line[0] !== '#') { $found = ['MALUMAIL_API_KEY' => $line]; break; }
            }
        }
        if (!empty($found['MALUMAIL_API_KEY'])) { $source = $path; break; }
        $found = [];
    }
    $key = (string) ($found['MALUMAIL_API_KEY'] ?? '');
    if ($key === '' && !empty($kernelEnv['MALUMAIL_API_KEY'])) { $key = (string) $kernelEnv['MALUMAIL_API_KEY']; $source = "the kernel's config/.env"; }
    return [
        'MALUMAIL_API_KEY' => $key,
        'MAIL_FROM' => (string) ($found['MAIL_FROM'] ?? $kernelEnv['MAIL_FROM'] ?? ''),
        'MAIL_FROM_NAME' => (string) ($found['MAIL_FROM_NAME'] ?? $kernelEnv['MAIL_FROM_NAME'] ?? ''),
        'source' => $source,
    ];
}
function http_status(string $url, string $host = ''): int
{
    $ch = curl_init($url);
    curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_CONNECTTIMEOUT => 2, CURLOPT_TIMEOUT => 3, CURLOPT_NOBODY => false,
        CURLOPT_HTTPHEADER => $host !== '' ? ['Host: ' . $host] : [], CURLOPT_FOLLOWLOCATION => false]);
    curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    return $code;
}
function port_taken(int $port): bool
{
    [, $out] = q("ss -ltnH 'sport = :{$port}'");
    return trim($out) !== '';
}
function render_template(string $text, array $vars): array
{
    $count = 0;
    $rendered = preg_replace_callback('/\{\{([A-Z][A-Z0-9_]*)\}\}/', static function (array $m) use ($vars, &$count): string {
        $count++;
        return (string) ($vars[$m[1]] ?? $m[0]);
    }, $text);
    $left = preg_match_all('/\{\{[A-Z][A-Z0-9_]*\}\}/', $rendered, $mm) ? array_unique($mm[0]) : [];
    return [$rendered, $count, $left];
}

// ---- 0. the kernel, the super-admin, the manifest ---------------------------------------------------------------
$pdo = db();
$kernelEnv = env_file_read($KERNEL . '/config/.env');
$by = null;
if (isset($opts['by']) && is_string($opts['by'])) {
    $by = find_member_by_email($pdo, normalize_email($opts['by']));
} else {
    $by = $pdo->query("SELECT * FROM members WHERE business_role = 'super_admin' AND member_kind = 'human' AND status = 'active' ORDER BY id LIMIT 1")->fetch() ?: null;
}
if ($by === null || ($by['business_role'] ?? '') !== 'super_admin') {
    stop('super-admin', 'the install is recorded under a super-admin: --by <email>.');
}
$byId = (int) $by['id'];
$_SESSION['member_id'] = $byId;
$_SESSION['member_role'] = $by['role'] ?? 'organizer';
db_apply_context($pdo);

$domain = (string) ($opts['domain'] ?? '');
if ($domain === '') {
    $host = (string) ($kernelEnv['APP_HOST'] ?? $kernelEnv['OS_HOST'] ?? '');
    $domain = $host !== '' ? preg_replace('/^[^.]+\./', '', $host) : '';
}
if ($domain === '') { stop('domain', 'no business domain: --domain <domain> (APP_HOST is not set in the kernel\'s config/.env).'); }
$scheme = (string) ($opts['scheme'] ?? 'http');
if (!in_array($scheme, ['http', 'https'], true)) { stop('scheme', '--scheme is http or https, not ' . json_encode($scheme) . '.'); }
$tenant = preg_replace('/[^a-z0-9_]/', '', strtolower((string) ($opts['tenant'] ?? explode('.', $domain)[0])));

// The manifest: from the directory, or from a clone of the URL into /srv/apps/<key> (the key is read first from a shallow clone).
$isUrl = preg_match('#^(https?://|git@|ssh://)#', $source) === 1;
$srcDir = $isUrl ? '' : rtrim(realpath($source) ?: $source, '/');
if (!$isUrl && !is_file($srcDir . '/maludb-os.json')) { stop('manifest', "no maludb-os.json in {$srcDir}."); }
if ($isUrl) {
    $tmp = sys_get_temp_dir() . '/app-install-' . substr(sha1($source), 0, 8);
    if (!is_file($tmp . '/maludb-os.json')) {
        [$c, $o] = q('git clone --depth 1 ' . (isset($opts['ref']) ? '--branch ' . escapeshellarg((string) $opts['ref']) . ' ' : '') . escapeshellarg($source) . ' ' . escapeshellarg($tmp));
        if ($c !== 0) { stop('manifest', "could not read the repository: {$o}"); }
    }
    $srcDir = $tmp;
}
$m = json_decode((string) file_get_contents($srcDir . '/maludb-os.json'), true);
if (!is_array($m)) { stop('manifest', 'maludb-os.json is not valid JSON.'); }
if (($m['schema'] ?? '') !== 'maludb-os.application/1') { stop('manifest', 'unknown schema ' . json_encode($m['schema'] ?? null) . ' — this installer knows maludb-os.application/1.'); }
if (empty($m['sso']['path'])) { stop('manifest', 'no sso.path — an application without sso cannot be signed in to; refused.'); }
$key = strtolower((string) ($m['catalog_key'] ?? ''));
if (!preg_match('/^[a-z][a-z0-9_]{1,31}$/', $key)) { stop('manifest', 'catalog_key must be lowercase letters, digits and underscores.'); }
$name = (string) ($m['name'] ?? ucfirst($key));
$label = (string) ($m['vhost']['label'] ?? $key);
$fqdn = $label . '.' . $domain;
$appUrl = $scheme . '://' . $fqdn;
$A = '/srv/apps/' . $key;
$dbName = $tenant . '_' . (string) ($m['database']['suffix'] ?? $key);
$roles = (array) ($m['database']['roles'] ?? ['rw' => $key . '_rw', 'records_ro' => $key . '_records_ro', 'activity_ro' => $key . '_activity_ro']);
$portEnvs = ['APP_INTERNAL_PORT' => (string) ($m['vhost']['internal_port_env'] ?? 'APP_INTERNAL_PORT')];
foreach ((array) ($m['endpoints'] ?? []) as $e) {
    if (!empty($e['port_env'])) { $portEnvs[(string) $e['port_env']] = (string) $e['port_env']; }
}
$hire = !empty($opts['hire-agents']);
$grantStanding = !empty($opts['grant-standing-departments']);

echo ($APPLY ? "Applying" : "Plan for") . " {$name} ({$key}) at {$A}, {$appUrl}, database {$dbName}, as {$by['email']}\n\n";

// ---- 1. the code at /srv/apps/<key> ----------------------------------------------------------------------------
if (is_file($A . '/maludb-os.json')) {
    say('code', 'done', "{$A} holds the application" . (realpath($srcDir) !== realpath($A) ? ' (the source given is elsewhere; the installed copy is used)' : ''));
} else {
    if (is_dir($A)) { stop('code', "{$A} exists but holds no maludb-os.json — not overwriting; remove or fix it first."); }
    $cmd = $isUrl
        ? 'git clone ' . (isset($opts['ref']) ? '--branch ' . escapeshellarg((string) $opts['ref']) . ' ' : '') . escapeshellarg($source) . ' ' . escapeshellarg($A)
        : (is_dir($srcDir . '/.git') ? 'git clone ' . escapeshellarg($srcDir) . ' ' . escapeshellarg($A) : 'cp -a ' . escapeshellarg($srcDir) . ' ' . escapeshellarg($A));
    say('code', 'todo', "put the application at {$A}");
    [$c, $o] = sh('mkdir -p /srv/apps && ' . $cmd);
    if ($c !== 0) { stop('code', $o); }
    $owner = (string) (getenv('SUDO_USER') ?: 'www-data');
    sh('chown -R ' . escapeshellarg($owner) . ':www-data ' . escapeshellarg($A) . ' && chmod 750 ' . escapeshellarg($A . '/config') . ' 2>/dev/null; mkdir -p ' . escapeshellarg($A . '/config') . ' && chown ' . escapeshellarg($owner) . ':www-data ' . escapeshellarg($A . '/config'));
}
// The web user writes the application's storage/ (HR, Projects) or logs/ (an adopted application: ZozoCal).
foreach (['storage', 'logs'] as $writable) {
    if (is_dir($A . '/' . $writable) || is_dir($srcDir . '/' . $writable)) {
        // Owned by www-data, not merely writable: the installer runs as root, to whom everything is writable.
        $owner = @fileowner($A . '/' . $writable);
        if (!$APPLY || $owner === false || (posix_getpwuid($owner)['name'] ?? '') !== 'www-data') { sh('mkdir -p ' . escapeshellarg($A . '/' . $writable) . ' && chown -R www-data:www-data ' . escapeshellarg($A . '/' . $writable), true); }
    }
}

// ---- 2. dependencies ---------------------------------------------------------------------------------------------
if (is_file($A . '/composer.json') && !is_dir($A . '/vendor')) {
    say('dependencies', 'todo', 'composer install --no-dev');
    [$c, $o] = sh('cd ' . escapeshellarg($A) . ' && composer install --no-dev --optimize-autoloader --no-interaction');
    if ($c !== 0) { stop('dependencies', $o); }
}
// The Python runtime: by convention mcp/*.py with mcp/venv and mcp/requirements.txt; an application whose services live
// elsewhere (an adopted htmx-php-builder application: services/ and services/.venv) says so in maludb-os.json
// `runtime.python` = {"dir", "venv", "requirements"} (relative to the repository; 2026-10-04).
$py = (array) ($m['runtime']['python'] ?? []);
$pyDir = trim((string) ($py['dir'] ?? 'mcp'), '/');
$pyVenv = trim((string) ($py['venv'] ?? ($pyDir . '/venv')), '/');
$pyReq = trim((string) ($py['requirements'] ?? ($pyDir . '/requirements.txt')), '/');
$hasMcp = glob($A . '/' . $pyDir . '/*.py') !== [] || glob($srcDir . '/' . $pyDir . '/*.py') !== [] || glob($A . '/' . $pyDir . '/*/*.py') !== [];
if ($hasMcp) {
    if (is_file($A . '/' . $pyVenv . '/bin/python')) {
        say('venv', 'done', $A . '/' . $pyVenv);
    } else {
        $req = is_file($A . '/' . $pyReq) ? $A . '/' . $pyReq : $KERNEL . '/mcp/requirements.txt';
        say('venv', 'todo', "python3 -m venv {$A}/{$pyVenv} and install " . (str_starts_with($req, $A) ? substr($req, strlen($A) + 1) : 'the kernel\'s mcp/requirements.txt'));
        [$c, $o] = sh('python3 -m venv ' . escapeshellarg($A . '/' . $pyVenv) . ' && ' . escapeshellarg($A . '/' . $pyVenv . '/bin/pip') . ' install -q -r ' . escapeshellarg($req));
        if ($c !== 0) { stop('venv', $o); }
        sh('chown -R www-data:www-data ' . escapeshellarg($A . '/' . $pyVenv), true);
    }
}

// ---- 3. database, roles, migrations ------------------------------------------------------------------------------
$existingEnv = env_file_read($A . '/config/.env');
[, $dbExists] = psql_ro("SELECT 1 FROM pg_database WHERE datname = '" . $dbName . "'");
$dbExists = trim($dbExists) === '1';
$passwords = [];
$migrationsDir = $A . '/' . trim((string) ($m['database']['migrations'] ?? 'db'), '/');
$migrations = glob($migrationsDir . '/*.sql') ?: glob($srcDir . '/' . trim((string) ($m['database']['migrations'] ?? 'db'), '/') . '/*.sql') ?: [];
sort($migrations);
// An application whose schema needs more than "db/*.sql in order as postgres" (roles per file, an extension's memory schema,
// a seed row — an adopted application) ships an idempotent provisioning script and names it in maludb-os.json
// `database.provision` (2026-10-04). The installer creates the database and the roles, then runs the script as root with
// DB_NAME, DB_RW_ROLE, DB_RECORDS_ROLE, DB_ACTIVITY_ROLE, APP_DIR, APP_KEY, APP_NAME and TENANT in its environment; on an
// existing database it runs it again (the script must be safe to re-run — that is how an upgrade applies new files).
$provision = (string) ($m['database']['provision'] ?? '');
$provisionPath = $provision !== '' ? (is_file($A . '/' . $provision) ? $A . '/' . $provision : $srcDir . '/' . $provision) : '';
if ($provision !== '' && !is_file($provisionPath)) { stop('database', "database.provision names {$provision}, which is not in the repository."); }
$provisionCmd = static function () use ($provisionPath, $dbName, $roles, $A, $key, $name, $tenant): string {
    $env = ['DB_NAME' => $dbName, 'DB_RW_ROLE' => (string) $roles['rw'], 'DB_RECORDS_ROLE' => (string) ($roles['records_ro'] ?? ''),
            'DB_ACTIVITY_ROLE' => (string) ($roles['activity_ro'] ?? ''), 'APP_DIR' => $A, 'APP_KEY' => $key, 'APP_NAME' => $name, 'TENANT' => $tenant];
    $pairs = [];
    foreach ($env as $k => $v) { $pairs[] = $k . '=' . escapeshellarg($v); }
    return 'env ' . implode(' ', $pairs) . ' bash ' . escapeshellarg($provisionPath);
};
if ($dbExists) {
    if ($provision !== '') {
        say('database', 'todo', "{$dbName} exists — re-run {$provision} (idempotent: applies what is new)");
        [$c, $o] = sh($provisionCmd());
        if ($APPLY && $c !== 0) { stop('database', "{$provision}: {$o}"); }
    } else {
        say('database', 'done', "{$dbName} exists (" . count($migrations) . ' migration files in the repository; an upgrade applies the new ones by hand, in order)');
    }
} else {
    say('database', 'todo', "create {$dbName} owned by {$roles['rw']}, the three roles, then " . ($provision !== '' ? "run {$provision}" : count($migrations) . ' migrations in order'));
    foreach ($roles as $r) {
        [$c, $o] = psql("DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{$r}') THEN CREATE ROLE {$r} LOGIN; END IF; END \$\$;");
        if ($APPLY && $c !== 0) { stop('database', $o); }
    }
    [$c, $o] = psql("CREATE DATABASE {$dbName} OWNER {$roles['rw']}");
    if ($APPLY && $c !== 0) { stop('database', $o); }
    if ($provision !== '') {
        [$c, $o] = sh($provisionCmd());
        if ($APPLY && $c !== 0) { stop('database', "{$provision}: {$o}"); }
        if ($APPLY) { say('database', 'ok', "{$provision} ran"); }
    } else {
        foreach ($migrations as $f) {
            if (!$APPLY) { continue; }
            [$c, $o] = q('runuser -u postgres -- psql -v ON_ERROR_STOP=1 -q -d ' . escapeshellarg($dbName) . ' -f ' . escapeshellarg($f));
            if ($c !== 0) { stop('database', basename($f) . ": {$o}"); }
        }
        if ($APPLY) { say('database', 'ok', count($migrations) . ' migrations applied'); }
    }
}
// Role passwords: set when the application has no .env yet (a fresh install, or a database made by hand), or when asked with
// --rotate-db-passwords (a scratch install's passwords, written down in its proof scripts, survived apply: ProcessCore,
// 2026-10-09) — never printed; the services are restarted afterwards so they read the new ones.
$rotate = !empty($opts['rotate-db-passwords']);
$needPasswords = $rotate || !isset($existingEnv['DB_PASSWORD']) || $existingEnv['DB_PASSWORD'] === '';
if ($needPasswords) {
    say('db-roles', 'todo', ($rotate ? 'rotate the passwords of ' : 'set fresh passwords on ') . implode(', ', $roles) . ' (written to config/.env only)');
    foreach ($roles as $which => $r) {
        $passwords[$which] = bin2hex(random_bytes(24));
        [$c, $o] = psql("ALTER ROLE {$r} WITH LOGIN PASSWORD '{$passwords[$which]}'");
        if ($APPLY && $c !== 0) { stop('db-roles', $o); }
    }
} else {
    say('db-roles', 'done', 'config/.env already carries the roles\' passwords');
}

// ---- 4. ports ------------------------------------------------------------------------------------------------------
$ports = [];
$next = 8100;
$pick = static function () use (&$next, &$ports): int {
    while (port_taken($next) || in_array($next, $ports, true)) { $next++; }
    $ports[] = $next;
    return $next++;
};
foreach ($portEnvs as $envKey) {
    if (isset($existingEnv[$envKey]) && $existingEnv[$envKey] !== '') { $ports[$envKey] = (int) $existingEnv[$envKey]; }
}
foreach ($portEnvs as $envKey) {
    if (!isset($ports[$envKey])) { $ports[$envKey] = $pick(); }
}
$ports = array_filter($ports, 'is_string', ARRAY_FILTER_USE_KEY);
say('ports', isset($existingEnv['APP_INTERNAL_PORT']) ? 'done' : 'todo', implode(', ', array_map(static fn ($k, $v) => "{$k}={$v}", array_keys($ports), $ports)));

// ---- 5. config/.env ------------------------------------------------------------------------------------------------
$envPath = $A . '/config/.env';
$required = (array) ($m['env']['required'] ?? []);
$values = [
    'APP_ENV' => 'production', 'APP_DEBUG' => '0', 'APP_NAME' => $name, 'APP_URL' => $appUrl, 'APP_KEY' => $key,
    'DB_HOST' => '127.0.0.1', 'DB_PORT' => '5432', 'DB_NAME' => $dbName, 'DB_USER' => (string) $roles['rw'],
    'MCP_RECORDS_DB_USER' => (string) ($roles['records_ro'] ?? ''), 'MCP_ACTIVITY_DB_USER' => (string) ($roles['activity_ro'] ?? ''),
    'ACTION_TOKEN_KEY' => (string) ($kernelEnv['ACTION_TOKEN_KEY'] ?? ''), 'ACTIONS_RELAY_KEY' => (string) ($kernelEnv['ACTIONS_RELAY_KEY'] ?? ''),
    'OS_INTERNAL_URL' => 'http://127.0.0.1:8080', 'OS_LAUNCHER_URL' => $scheme . '://' . (string) ($kernelEnv['APP_HOST'] ?? ('app.' . $domain)) . '/',
    'MALUDB_API_URL' => (string) ($kernelEnv['MALUDB_API_URL'] ?? 'http://127.0.0.1:8000'),
] + $ports;
if ($passwords !== []) {
    $values['DB_PASSWORD'] = $passwords['rw'] ?? '';
    $values['MCP_RECORDS_DB_PASSWORD'] = $passwords['records_ro'] ?? '';
    $values['MCP_ACTIVITY_DB_PASSWORD'] = $passwords['activity_ro'] ?? '';
}
if (!empty($m['identity']['enabled_env'])) { $values[(string) $m['identity']['enabled_env']] = '1'; }
$missing = array_values(array_filter($required, static fn (string $k): bool => !isset($existingEnv[$k]) || $existingEnv[$k] === ''));
$missing = array_values(array_diff($missing, ['OS_APPLICATION_TOKEN']));    // minted in step 9
// MaluMail: the mail keys the manifest names (required or optional) that config/.env lacks or leaves empty — the key from the
// installer's ~/.malumail or the kernel's config/.env (malumail_values()), the sender from the same or the business's default.
$mailKeys = ['MALUMAIL_API_KEY', 'MAIL_FROM', 'MAIL_FROM_NAME'];
$mailable = array_values(array_intersect($mailKeys, array_merge($required, (array) ($m['env']['optional'] ?? []))));
$mailMissing = array_values(array_filter($mailable, static fn (string $k): bool => !isset($existingEnv[$k]) || $existingEnv[$k] === ''));
if ($mailable !== []) {
    $mail = malumail_values($kernelEnv, $KERNEL);
    $keyKnown = $mail['MALUMAIL_API_KEY'] !== '' || (isset($existingEnv['MALUMAIL_API_KEY']) && $existingEnv['MALUMAIL_API_KEY'] !== '');
    if ($mailMissing === []) {
        say('mail', 'done', 'config/.env carries the MaluMail key and the sender');
    } elseif (!$keyKnown) {
        say('mail', 'note', 'no MaluMail key: put it in ~/.malumail (one line) or the kernel\'s config/.env and apply again — the application sends no mail until MALUMAIL_API_KEY is set');
        $mailMissing = [];
    } else {
        $values['MALUMAIL_API_KEY'] = $mail['MALUMAIL_API_KEY'];
        $values['MAIL_FROM'] = $mail['MAIL_FROM'] !== '' ? $mail['MAIL_FROM'] : 'no-reply@' . $domain;
        $values['MAIL_FROM_NAME'] = $mail['MAIL_FROM_NAME'] !== '' ? $mail['MAIL_FROM_NAME'] : $name;
        say('mail', 'todo', 'write ' . implode(', ', $mailMissing) . ' to config/.env'
            . (in_array('MALUMAIL_API_KEY', $mailMissing, true) ? ' (the key from ' . $mail['source'] . ', never shown)' : ''));
    }
}
$missing = array_values(array_diff($missing, $mailMissing));    // a required mail key is written by the mail step, not left empty
// Keys whose value the INSTALLER decides are the installer's: a config/.env left by a scratch install (the developer's database,
// a loopback APP_URL, a dev signing key) must not survive apply — ProcessCore's did on 2026-10-09: the application kept writing to
// processcore_dev and refused every hand-off as expired because its ACTION_TOKEN_KEY was not the kernel's. Rewritten when they
// differ, named in a todo line, values never shown. Secrets the installer generates ONCE (the roles' passwords, TOTP_KEY,
// DUMMY_PASSWORD_HASH) and the ports stay as they are.
$installerOwned = ['APP_ENV', 'APP_NAME', 'APP_URL', 'APP_KEY', 'DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER', 'MCP_RECORDS_DB_USER', 'MCP_ACTIVITY_DB_USER',
    'ACTION_TOKEN_KEY', 'ACTIONS_RELAY_KEY', 'OS_INTERNAL_URL', 'OS_LAUNCHER_URL', 'MALUDB_API_URL'];
if (!empty($m['identity']['enabled_env'])) { $installerOwned[] = (string) $m['identity']['enabled_env']; }
$sharedKeys = array_values(array_filter($installerOwned,
    static fn (string $k): bool => isset($values[$k]) && $values[$k] !== '' && isset($existingEnv[$k]) && $existingEnv[$k] !== '' && !hash_equals($values[$k], $existingEnv[$k])));
if ($sharedKeys !== []) {
    say('config', 'todo', implode(', ', $sharedKeys) . ' in config/.env differ' . (count($sharedKeys) === 1 ? 's' : '') . " from this install's values (a scratch install's leftovers) — rewritten; the roles' passwords and the ports are kept");
}
$passwordKeys = $passwords !== [] ? ['DB_PASSWORD', 'MCP_RECORDS_DB_PASSWORD', 'MCP_ACTIVITY_DB_PASSWORD'] : [];   // fresh or rotated: always written
$write = array_values(array_unique(array_merge($missing, $mailMissing, $sharedKeys, $passwordKeys)));
if ($missing === []) {
    say('config', 'done', array_intersect($mailMissing, $required) === [] ? 'config/.env carries every required key' : 'config/.env carries every required key but the mail keys, which the mail step writes');
} else {
    // The MaluDB token is minted for the application by proving the tenant's memory login; failing that, the kernel's is shared.
    if (in_array('MALUDB_API_TOKEN', $missing, true)) {
        $minted = null;
        if (!empty($kernelEnv['MALUDB_MEMORY_DB']) && !empty($kernelEnv['MALUDB_MEMORY_USER']) && !empty($kernelEnv['MALUDB_MEMORY_PASSWORD'])) {
            $ch = curl_init(rtrim($values['MALUDB_API_URL'], '/') . '/v1/tokens');
            curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 5, CURLOPT_POST => true, CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
                CURLOPT_POSTFIELDS => json_encode(['pg_dbname' => $kernelEnv['MALUDB_MEMORY_DB'], 'pg_user' => $kernelEnv['MALUDB_MEMORY_USER'], 'pg_password' => $kernelEnv['MALUDB_MEMORY_PASSWORD'], 'label' => $name . ' (application)'])]);
            $resp = json_decode((string) curl_exec($ch), true);
            curl_close($ch);
            $minted = is_array($resp) ? ($resp['token'] ?? $resp['access_token'] ?? null) : null;
        }
        $values['MALUDB_API_TOKEN'] = is_string($minted) && $minted !== '' ? $minted : (string) ($kernelEnv['MALUDB_API_TOKEN'] ?? '');
        say('maludb-token', is_string($minted) && $minted !== '' ? 'todo' : 'note', is_string($minted) && $minted !== '' ? 'minted for the application' : 'the tenant\'s memory login is not in the kernel\'s config/.env — the kernel\'s MaluDB token is shared');
    }
    $unknown = array_values(array_filter($missing, static fn (string $k): bool => !isset($values[$k])));
    say('config', 'todo', 'write ' . count($missing) . ' missing keys to config/.env' . ($unknown !== [] ? ' — no value known for ' . implode(', ', $unknown) . ' (left empty; fill them in)' : ''));
}
if ($write !== [] && $APPLY) {
    $lines = is_file($envPath) ? (string) file_get_contents($envPath) : '';
    foreach ($write as $k) { $lines = env_lines_set($lines, $k, (string) ($values[$k] ?? '')); }
    if (@file_put_contents($envPath, $lines) === false) { stop('config', "could not write {$envPath}"); }
    $owner = (string) (getenv('SUDO_USER') ?: 'root');
    sh('chown ' . escapeshellarg($owner) . ':www-data ' . escapeshellarg($envPath) . ' && chmod 640 ' . escapeshellarg($envPath), true);
}
$env = $APPLY ? env_file_read($envPath) : ($existingEnv + $values);

// ---- 6. the vhost and the name ----------------------------------------------------------------------------------
$vars = ['DOMAIN' => $domain, 'APP_DIR' => $A, 'APP_KEY' => $key, 'APP_LABEL' => $label, 'APP_FQDN' => $fqdn] + $env;
$deployDir = is_dir($A . '/deploy') ? $A . '/deploy' : $srcDir . '/deploy';
$vhostSrc = null;
foreach ([$deployDir . '/apache-' . $key . '.conf', $deployDir . '/' . $key . '.conf', $deployDir . '/apache.conf'] as $cand) {
    if (is_file($cand)) { $vhostSrc = $cand; break; }
}
if ($vhostSrc === null) {
    say('vhost', 'note', 'no Apache vhost in deploy/ — the application is not served by name until one exists');
} else {
    [$rendered, $filled, $left] = render_template((string) file_get_contents($vhostSrc), $vars);
    $target = '/etc/apache2/sites-available/' . $key . '.conf';
    $note = $filled === 0 ? ' (no placeholders — installed as written; check its ServerName and ports)' : ($left !== [] ? ' — unfilled: ' . implode(' ', $left) : '');
    if (is_file($target) && file_get_contents($target) === $rendered) {
        say('vhost', 'done', $target . ' is current' . $note);
    } else {
        say('vhost', 'todo', (is_file($target) ? 'update ' : 'install ') . $target . ', a2ensite, configtest, reload' . $note);
        if ($APPLY) {
            // Never leave Apache with a broken config on disk (the 2026-10-02 outage; the cidery apply of 2026-10-04 stopped on a
            // directive whose module was not enabled): keep the previous file, test the new one enabled, and on failure put the
            // previous one back (or disable a new site) BEFORE stopping — a later reload or restart must still succeed.
            $previous = is_file($target) ? (string) file_get_contents($target) : null;
            $wasEnabled = is_link('/etc/apache2/sites-enabled/' . $key . '.conf');
            if (@file_put_contents($target, $rendered) === false) { stop('vhost', "could not write {$target}"); }
            [$c, $o] = sh("a2ensite -q {$key} && apachectl configtest");
            if ($c !== 0) {
                if ($previous !== null) { file_put_contents($target, $previous); } else { @unlink($target); }
                if (!$wasEnabled) { sh("a2dissite -q {$key}", true); }
                [$c2, $o2] = sh('apachectl configtest', true);
                stop('vhost', trim($o) . "\n" . ($previous !== null ? 'the previous vhost was put back' : 'the new site was disabled again') . ' — Apache\'s config is ' . ($c2 === 0 ? 'valid' : 'STILL INVALID: ' . trim($o2)) . '. Fix deploy/' . basename($vhostSrc) . ' (a directive may need a module: apache2ctl -M) and run apply again.');
            }
            sh('systemctl reload apache2');
        }
    }
}
[$c] = q('getent hosts ' . escapeshellarg($fqdn));
if ($c === 0) {
    say('dns', 'done', "{$fqdn} resolves");
} else {
    say('dns', 'todo', "{$fqdn} does not resolve yet — a loopback line goes in /etc/hosts until the owner's DNS exists");
    sh('printf "127.0.0.1\t%s\n" ' . escapeshellarg($fqdn) . ' >> /etc/hosts');
}

// ---- 7. services -------------------------------------------------------------------------------------------------
$units = [];
foreach ((array) ($m['services'] ?? []) as $rel) {
    $src = is_file($A . '/' . $rel) ? $A . '/' . $rel : $srcDir . '/' . $rel;
    if (!is_file($src)) { say('services', 'note', "{$rel} is not in the repository — skipped"); continue; }
    [$rendered, , $left] = render_template((string) file_get_contents($src), $vars);
    $unit = basename($rel);
    $target = '/etc/systemd/system/' . $unit;
    $units[] = $unit;
    if (is_file($target) && file_get_contents($target) === $rendered) { continue; }
    say('services', 'todo', (is_file($target) ? 'update ' : 'install ') . $unit . ($left !== [] ? ' — unfilled: ' . implode(' ', $left) : ''));
    if ($APPLY && @file_put_contents($target, $rendered) === false) { stop('services', "could not write {$target}"); }
    $changed = true;
}
if ($units !== []) {
    $enable = array_values(array_filter($units, static fn (string $u): bool => str_ends_with($u, '.timer') || !in_array(preg_replace('/\.service$/', '.timer', $u), $units, true)));
    if (!empty($changed)) { sh('systemctl daemon-reload'); }
    [$c, $o] = q('systemctl is-active ' . implode(' ', array_map('escapeshellarg', $enable)));
    if (!empty($changed) || $c !== 0) {
        say('services', 'todo', 'enable --now ' . implode(' ', $enable));
        [$c, $o] = sh('systemctl enable -q --now ' . implode(' ', array_map('escapeshellarg', $enable)) . (!empty($changed) ? ' && systemctl restart ' . implode(' ', array_map('escapeshellarg', $enable)) : ''));
        if ($c !== 0) { stop('services', $o); }
    } else {
        say('services', 'done', count($units) . ' units installed and active');
    }
}
// Each MCP port answers; the health endpoint answers 200 on the loopback port.
$answering = [];
foreach ((array) ($m['endpoints'] ?? []) as $e) {
    $port = !empty($e['port_env']) ? (int) ($env[(string) $e['port_env']] ?? 0) : (int) ($env['APP_INTERNAL_PORT'] ?? 0);
    if ($port === 0) { continue; }
    $path = ($e['kind'] ?? '') === 'mcp' ? '/mcp' : (string) ($e['path'] ?? '/');
    $code = 0;
    for ($i = 0; $i < ($APPLY ? 10 : 1) && $code === 0; $i++) {
        $code = http_status("http://127.0.0.1:{$port}{$path}", ($e['kind'] ?? '') === 'mcp' ? '' : $fqdn);
        if ($code === 0 && $APPLY) { sleep(2); }
    }
    $answering[(string) $e['name']] = $code;
}
foreach ($answering as $n => $code) {
    say('answers', $code > 0 ? 'done' : ($APPLY ? 'STOP' : 'todo'), "{$n}: " . ($code > 0 ? "HTTP {$code}" : 'not answering yet'));
}
if ($APPLY && in_array(0, $answering, true)) { stop('answers', 'an endpoint is not answering — registration waits for it.'); }

// ---- 8. registration in the kernel --------------------------------------------------------------------------------
$areaId = null;
foreach (find_business_areas($pdo) as $area) {
    if (strcasecmp((string) $area['name'], (string) ($m['business_area'] ?? '')) === 0) { $areaId = (int) $area['business_area_id']; }
}
if ($areaId === null) {
    foreach (find_business_areas($pdo) as $area) { if ((string) $area['name'] === 'Operations') { $areaId = (int) $area['business_area_id']; } }
}
$catalog = find_catalog_entry($pdo, $key);
if ($catalog !== null) {
    say('catalog', 'done', "catalog entry {$key} (kind {$catalog['kind']})");
} else {
    say('catalog', 'todo', "catalog entry {$key}, kind ours");
    if ($APPLY) {
        $pdo->prepare('INSERT INTO application_catalog (catalog_key, name, description, icon, business_area_id, kind, vendor, category)
                       VALUES (:k, :n, :d, :i, :a, \'ours\', NULL, :c)')
            ->execute(['k' => $key, 'n' => $name, 'd' => (string) ($m['description'] ?? ''), 'i' => (string) ($m['icon'] ?? 'feather-box'), 'a' => $areaId, 'c' => (string) ($m['category'] ?? 'other')]);
        log_activity($pdo, 'application_catalog.save', 'application_catalog', 0, ['source' => 'cron', 'after' => ['catalog_key' => $key, 'kind' => 'ours', 'by' => 'bin/app_install.php']]);
    }
}
$st = $pdo->prepare("SELECT * FROM applications WHERE app_key = :k AND status <> 'retired'");
$st->execute(['k' => $key]);
$app = $st->fetch() ?: null;
if ($app !== null) {
    say('application', 'done', "application {$app['id']} ({$app['status']})");
} else {
    say('application', 'todo', "register {$name} with url {$appUrl}, sso {$m['sso']['path']}, scope_kind " . ($m['scopes']['kind'] ?? 'none'));
    if ($APPLY) {
        $office = $pdo->query("SELECT location_id FROM applications WHERE name = 'Business OS' ORDER BY id LIMIT 1")->fetchColumn();
        $frontOffice = $pdo->query("SELECT id FROM departments WHERE system_key = 'front_office'")->fetchColumn();
        $row = upsert_application($pdo, null, [
            'name' => $name, 'app_key' => $key, 'catalog_key' => $key, 'category' => (string) ($m['category'] ?? 'other'),
            'description' => (string) ($m['description'] ?? ''), 'vendor' => null, 'is_self_hosted' => true,
            'location_id' => $office !== false ? (int) $office : null, 'owner_department_id' => $frontOffice !== false ? (int) $frontOffice : null,
            'owner_member_id' => null, 'url' => $appUrl, 'version' => (string) ($m['version'] ?? ''),
            'criticality' => in_array($m['criticality'] ?? '', ['low', 'normal', 'high', 'critical'], true) ? $m['criticality'] : 'normal',
            'notes' => 'Installed by bin/app_install.php from ' . $source, 'business_area_id' => $areaId, 'business_area_sent' => true,
            'scope_kind' => (string) ($m['scopes']['kind'] ?? 'none'), 'scope_kind_sent' => true,
            'sso_path' => (string) $m['sso']['path'], 'sso_logout_path' => (string) ($m['sso']['logout_path'] ?? ''),
            'directory_writes' => !empty($m['directory']['writes']), 'created_by' => $byId,
        ]);
        $st->execute(['k' => $key]);
        $app = $st->fetch() ?: null;
        if ($app === null) { stop('application', 'the application row was not created.'); }
        log_activity($pdo, 'application.create', 'application', (int) $app['id'], ['source' => 'cron', 'after' => ['name' => $name, 'app_key' => $key, 'url' => $appUrl, 'by' => 'bin/app_install.php']]);
    }
}
$appId = $app !== null ? (int) $app['id'] : 0;
$have = [];
if ($appId > 0) { foreach (find_application_endpoints($pdo, $appId) as $e) { $have[(string) $e['name']] = $e; } }
foreach ((array) ($m['endpoints'] ?? []) as $e) {
    $n = (string) $e['name'];
    $url = $appUrl . (string) ($e['path'] ?? '/');
    if (isset($have[$n])) { continue; }
    if (($answering[$n] ?? 0) === 0) { say('endpoints', 'note', "{$n} is not answering — not registered until it does"); continue; }
    say('endpoints', 'todo', "register {$n} ({$e['kind']}) at {$url}");
    if ($APPLY) {
        $row = upsert_application_endpoint($pdo, null, ['application_id' => $appId, 'name' => $n, 'kind' => (string) $e['kind'], 'url' => $url,
            'auth_kind' => (string) ($e['auth_kind'] ?? 'none'), 'agent_reachable' => !empty($e['agent_reachable']), 'mcp_surface_version' => (string) ($e['mcp_surface_version'] ?? ''), 'notes' => null]);
        log_activity($pdo, 'application_endpoint.save', 'application', $appId, ['source' => 'cron', 'after' => ['name' => $n, 'kind' => $e['kind'], 'url' => $url]]);
    }
}
if ($appId > 0 && count($have) === count((array) ($m['endpoints'] ?? []))) { say('endpoints', 'done', count($have) . ' endpoints registered'); }

// ---- 9. the application token, into config/.env, then the services restart --------------------------------------------
if (empty($env['OS_APPLICATION_TOKEN'])) {
    say('token', 'todo', 'mint the application token into config/.env (never shown) and restart the services');
    if ($APPLY) {
        if ($appId === 0) { stop('token', 'no application row.'); }
        $t = mint_application_token($pdo, $appId, $byId, $name . ' (application token)');
        log_activity($pdo, 'application.token_mint', 'application', $appId, ['source' => 'cron', 'after' => ['token_id' => $t['id'], 'by' => 'bin/app_install.php']]);
        $text = preg_replace('/^OS_APPLICATION_TOKEN=.*\n?/m', '', (string) file_get_contents($envPath));
        if (@file_put_contents($envPath, rtrim($text) . "\nOS_APPLICATION_TOKEN=" . $t['raw'] . "\n") === false) {
            stop('token', "could not write {$envPath} — revoke token {$t['id']} on the application's page and run again");
        }
        if ($units !== []) { sh('systemctl restart ' . implode(' ', array_map('escapeshellarg', array_filter($units, static fn (string $u): bool => str_ends_with($u, '.service') && !in_array(preg_replace('/\.service$/', '.timer', $u), $units, true))))); }
        $env = env_file_read($envPath);
    }
} else {
    say('token', 'done', 'config/.env carries OS_APPLICATION_TOKEN');
}

// ---- 10. roles from the application, then active -----------------------------------------------------------------------
if ($appId > 0) {
    $current = find_application_roles($pdo, $appId);
    if ($current !== [] && !$APPLY) {
        say('roles', 'done', count($current) . ' roles held (refreshed on apply)');
    } else {
        say('roles', $current === [] ? 'todo' : 'ok', 'read the roles and rights from the application (app_roles)');
        if ($APPLY) {
            try {
                $application = find_application($pdo, $appId);
                [$payload, $endpoint] = fetch_application_roles($pdo, $application ?? []);
                [$rolesRead, $errors] = validate_application_roles($payload);
                if ($errors !== []) { throw new RuntimeException(implode('; ', array_unique($errors))); }
                $pdo->beginTransaction();
                $outcome = apply_application_roles($pdo, $appId, $rolesRead);
                log_activity($pdo, 'application.roles_refresh', 'application', $appId, ['source' => 'cron', 'after' => ['endpoint' => $endpoint, 'roles' => array_column($rolesRead, 'key')] + $outcome]);
                $pdo->commit();
                say('roles', 'ok', count($rolesRead) . ' roles: ' . implode(', ', array_column($rolesRead, 'key')));
            } catch (Throwable $ex) {
                if ($pdo->inTransaction()) { $pdo->rollBack(); }
                say('roles', 'note', 'the application did not publish its roles: ' . $ex->getMessage() . ' — grants wait for them (application_roles_refresh on its page, or application_roles_set)');
            }
        }
    }
    if (($app['status'] ?? '') !== 'active') {
        say('status', 'todo', 'active');
        if ($APPLY) { set_application_status($pdo, $appId, 'active'); log_activity($pdo, 'application.status', 'application', $appId, ['source' => 'cron', 'after' => ['status' => 'active']]); }
    } else {
        say('status', 'done', 'active');
    }
}

// ---- 10b. what it shares with other applications, and what it asks to read (K7, db/161) ----------------------------------
if ($appId > 0 && (!empty($m['shares']) || !empty($m['reads']))) {
    require_once $KERNEL . '/app/features/applications/services.php';
    $haveShares = $pdo->prepare('SELECT count(*) FROM application_shares WHERE application_id = :a AND withdrawn_at IS NULL');
    $haveShares->execute(['a' => $appId]);
    $haveReads = $pdo->prepare('SELECT count(*) FROM application_connections WHERE consumer_id = :a AND revoked_at IS NULL');
    $haveReads->execute(['a' => $appId]);
    $wantShares = count((array) ($m['shares'] ?? []));
    $wantReads = count((array) ($m['reads'] ?? []));
    if ((int) $haveShares->fetchColumn() === $wantShares && (int) $haveReads->fetchColumn() >= $wantReads && !$APPLY) {
        say('services', 'done', "{$wantShares} shared tools, {$wantReads} reads proposed");
    } else {
        say('services', 'todo', "record {$wantShares} shared tools; propose {$wantReads} reads (a super-admin approves them: bin/app_connection.php)");
        if ($APPLY) {
            $sync = application_services_sync($pdo, $appId, (array) ($m['shares'] ?? []), (array) ($m['reads'] ?? []));
            say('services', 'ok', "{$sync['shares']} shared, {$sync['withdrawn']} withdrawn, {$sync['proposed']} reads proposed"
                . ($sync['waiting'] !== [] ? ' — waiting for ' . implode(', ', $sync['waiting']) : ''));
        }
    }
}

// ---- 11. the action registry on the kernel's actions server --------------------------------------------------------------
$registryRel = (string) ($m['actions']['registry'] ?? 'mcp/action_registry.json');
$registrySrc = is_file($A . '/' . $registryRel) ? $A . '/' . $registryRel : $srcDir . '/' . $registryRel;
if (!is_file($registrySrc)) {
    say('registry', 'note', "no {$registryRel} in the repository — the application's actions are not on the Actions MCP");
} else {
    $registry = json_decode((string) file_get_contents($registrySrc), true) ?: [];
    $wrapperSrc = null;
    foreach ([$deployDir . '/kernel-registry-' . $key . '.json', $deployDir . '/kernel-registry.json'] as $cand) { if (is_file($cand)) { $wrapperSrc = $cand; break; } }
    $wrapper = $wrapperSrc !== null ? (json_decode((string) file_get_contents($wrapperSrc), true) ?: []) : [];
    $recordsPath = '/mcp/records';
    foreach ((array) ($m['endpoints'] ?? []) as $e) { if (($e['kind'] ?? '') === 'mcp' && stripos((string) $e['name'], 'records') !== false) { $recordsPath = (string) ($e['path'] ?? $recordsPath); } }
    $file = ['schema' => 'maludb-os.registry/1', 'app_key' => $key, 'name' => $name,
        'base_url' => 'http://127.0.0.1:' . (int) ($env['APP_INTERNAL_PORT'] ?? 0), 'records_url' => $appUrl . $recordsPath,
        'resolve' => (array) ($wrapper['resolve'] ?? []), 'registry' => $registry];
    $target = $KERNEL . '/mcp/registries/' . $key . '.json';
    // K55 (2026-10-11): every action gets the name it is served under on the kernel's ONE Actions MCP — its own name when no other
    // application and no kernel action uses it, else "<app_key>_<action>"; a name this application already had is kept, and no
    // other application's tool is ever renamed (app/features/applications/action_tool_names.php).
    require_once $KERNEL . '/app/features/applications/action_tool_names.php';
    $others = load_action_registries($KERNEL . '/mcp/registries');
    unset($others[$key]);
    $previousFile = is_file($target) ? (json_decode((string) file_get_contents($target), true) ?: null) : null;
    [$file, $toolClashes] = assign_registry_tool_names($key, $file, $previousFile, $others, kernel_action_names($KERNEL));
    $prefixed = array_filter(registry_built_actions($file), static fn (array $a): bool => isset($a['tool_name']) && $a['tool_name'] !== $a['action']);
    if ($prefixed !== []) {
        say('registry', 'note', count($prefixed) . " action(s) served as {$key}_<action> — another application or the kernel uses the name: "
            . implode(', ', array_map(static fn (array $a): string => (string) $a['action'], array_slice($prefixed, 0, 8))) . (count($prefixed) > 8 ? ', …' : ''));
    }
    foreach ($toolClashes as $act => $why) { say('registry', 'note', "action {$act}: {$why} — it will not be served (K55)"); }
    $json = json_encode($file, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n";
    $built = is_array($registry['actions'] ?? null) ? count(array_filter($registry['actions'], static fn (array $a): bool => !empty($a['built']))) : 0;
    if (is_file($target) && file_get_contents($target) === $json) {
        say('registry', 'done', basename($target) . " is current ({$built} built actions" . ($file['resolve'] === [] ? ', no resolve block' : '') . ')');
    } else {
        say('registry', 'todo', (is_file($target) ? 'refresh ' : 'write ') . "mcp/registries/{$key}.json ({$built} built actions)" . (empty($opts['no-restart']) ? ' and restart maludb-os-actions-mcp' : ''));
        if ($APPLY) {
            if (@file_put_contents($target, $json) === false) { stop('registry', "could not write {$target}"); }
            sh('chmod 644 ' . escapeshellarg($target) . ' && chown ' . escapeshellarg((string) (getenv('SUDO_USER') ?: 'root')) . ':www-data ' . escapeshellarg($target), true);
            if (empty($opts['no-restart'])) { sh('systemctl restart maludb-os-actions-mcp'); }
        }
    }
}

// ---- 12. skills, imported and assigned at application scope ------------------------------------------------------------------
foreach ((array) ($m['skills'] ?? []) as $rel) {
    $dir = is_dir($A . '/' . $rel) ? $A . '/' . $rel : $srcDir . '/' . $rel;
    $skillName = basename((string) $rel);
    if (!is_file($dir . '/SKILL.md')) { say('skills', 'note', "{$rel} has no SKILL.md — skipped"); continue; }
    $held = false;
    if ($appId > 0) {
        $st = $pdo->prepare("SELECT 1 FROM skill_assignments WHERE skill_name = :s AND scope_kind = 'application' AND application_id = :a AND revoked_at IS NULL");
        $st->execute(['s' => $skillName, 'a' => $appId]);
        $held = $st->fetchColumn() !== false;
    }
    if (!$APPLY) { say('skills', $held ? 'done' : 'todo', $skillName . ($held ? ' assigned at application scope (re-imported on apply: a changed bundle becomes a new version)' : ': import, assign at application scope')); continue; }
    [$ingested, $error] = import_skill_folder($pdo, $dir, $byId);
    if ($ingested === null) { say('skills', 'note', "{$skillName}: {$error}"); continue; }
    if (!$held && $appId > 0) {
        create_skill_assignment($pdo, ['skill_name' => $skillName, 'scope_kind' => 'application', 'application_id' => $appId, 'note' => "Shipped with {$name} (installed " . date('Y-m-d') . ')'], $byId);
        log_activity($pdo, 'skill.assign', 'application', $appId, ['source' => 'cron', 'after' => ['skill_name' => $skillName, 'scope_kind' => 'application']]);
    }
    say('skills', 'ok', $skillName . (!empty($ingested['reused']) ? ' unchanged' : ' ingested') . ($held ? '' : ', assigned'));
}

// ---- 13. approval policies for the manifest's approvals[] --------------------------------------------------------------------
$registryActions = isset($registry) && is_array($registry['actions'] ?? null) ? $registry['actions'] : [];
$policies = $pdo->query("SELECT action_pattern, category FROM approval_policies WHERE applies_to = 'agents' AND active")->fetchAll(PDO::FETCH_KEY_PAIR);
$newPolicies = 0;
foreach ((array) ($m['approvals'] ?? []) as $ap) {
    $action = (string) ($ap['action'] ?? '');
    $logEvent = (string) ($registryActions[$action]['log_event'] ?? '');
    if ($action === '' || $logEvent === '') { continue; }
    $covered = false;
    foreach ($policies as $pattern => $cat) {
        if (fnmatch((string) $pattern, $logEvent)) { $covered = true; }
    }
    if ($covered) { continue; }
    $newPolicies++;
    say('approvals', 'todo', "agents' {$logEvent} pauses for approval ({$ap['category']})");
    if ($APPLY) {
        $pdo->prepare("INSERT INTO approval_policies (name, category, action_pattern, applies_to, expires_after_hours, active, created_by)
                       VALUES (:n, :c, :p, 'agents', 72, true, :by)")
            ->execute(['n' => "Agents: {$name} — {$action}", 'c' => in_array($ap['category'] ?? '', ['deletion', 'money_out', 'external_send', 'other'], true) ? $ap['category'] : 'other', 'p' => $logEvent, 'by' => $byId]);
        log_activity($pdo, 'approval_policy.create', 'approval_policy', 0, ['source' => 'cron', 'after' => ['action_pattern' => $logEvent, 'category' => $ap['category'] ?? 'other', 'application' => $key]]);
    }
}
if ($newPolicies === 0) { say('approvals', 'done', count((array) ($m['approvals'] ?? [])) . ' approval categories, every one covered by a policy'); }

// ---- 14. grants: the installing super-admin as admin; the standing departments as members (K4) ------------------------------------
if ($appId > 0) {
    $roleRows = find_application_roles($pdo, $appId);
    $adminRole = null; $memberRole = null;
    foreach ($roleRows as $r) {
        if ($r['withdrawn_at'] !== null) { continue; }
        if (!empty($r['is_admin']) && $adminRole === null) { $adminRole = (string) $r['role_key']; }
        if (in_array($r['role_key'], ['member', 'user', 'write'], true)) { $memberRole = (string) $r['role_key']; }
    }
    if ($memberRole === null) { foreach ($roleRows as $r) { if ($r['withdrawn_at'] === null && empty($r['is_admin'])) { $memberRole = (string) $r['role_key']; } } }
    $grants = find_application_access($pdo, $appId);
    $hasAdmin = false;
    foreach ($grants as $g) { if ((int) ($g['member_id'] ?? 0) === $byId && ($g['capability'] ?? '') === 'admin') { $hasAdmin = true; } }
    $scoped = (string) ($m['scopes']['kind'] ?? 'none') !== 'none';
    if ($hasAdmin) {
        say('grant-admin', 'done', "{$by['email']} administers it");
    } elseif ($scoped) {
        // A grant on a scoped application names a site or department; a super-admin needs none — the kernel gives
        // them the admin role in every scope (app_member_role_keys), and the launcher shows them the application.
        say('grant-admin', 'done', "a super-admin holds the " . ($adminRole ?? 'admin') . ' role in every scope — no grant needed');
    } elseif ($roleRows === []) {
        say('grant-admin', 'note', 'no roles yet — the admin grant waits for them');
    } else {
        say('grant-admin', 'todo', "{$by['email']} as " . ($adminRole ?? 'admin'));
        if ($APPLY) {
            grant_application_access($pdo, $appId, ['member_id' => $byId, 'capability' => 'admin', 'roles' => $adminRole !== null ? [$adminRole] : [], 'note' => 'Installer (bin/app_install.php)'], $byId);
            log_activity($pdo, 'application_access.grant', 'application', $appId, ['source' => 'cron', 'after' => ['member_id' => $byId, 'capability' => 'admin', 'role_key' => $adminRole]]);
        }
    }
    if ($grantStanding && $scoped) {
        say('grant-depts', 'note', 'a scoped application: department grants name a scope — the super-admin grants them per scope on the Access tab');
    } elseif ($grantStanding) {
        $standing = $pdo->query('SELECT id, name FROM departments WHERE system_key IS NOT NULL AND archived_at IS NULL ORDER BY id')->fetchAll();
        $heldDepts = [];
        foreach ($grants as $g) { if (($g['department_id'] ?? null) !== null) { $heldDepts[(int) $g['department_id']] = true; } }
        $todo = array_values(array_filter($standing, static fn (array $d): bool => !isset($heldDepts[(int) $d['id']])));
        if ($todo === []) {
            say('grant-depts', 'done', count($standing) . ' standing departments hold it');
        } elseif ($roleRows === []) {
            say('grant-depts', 'note', 'no roles yet — the department grants wait for them');
        } else {
            say('grant-depts', 'todo', implode(', ', array_column($todo, 'name')) . ' at write as ' . ($memberRole ?? 'member'));
            if ($APPLY) {
                foreach ($todo as $d) {
                    grant_application_access($pdo, $appId, ['department_id' => (int) $d['id'], 'capability' => 'write', 'roles' => $memberRole !== null ? [$memberRole] : [], 'note' => 'Standing department (installed ' . date('Y-m-d') . ')'], $byId);
                    log_activity($pdo, 'application_access.grant', 'application', $appId, ['source' => 'cron', 'after' => ['department_id' => (int) $d['id'], 'capability' => 'write', 'role_key' => $memberRole]]);
                }
            }
        }
    }
}

// ---- 15. the agents: hired (--hire-agents) or proposed ------------------------------------------------------------------------
$agents = (array) ($m['agents'] ?? []);
if (isset($m['expert']) && $agents === []) { $agents = [['key' => 'expert'] + (array) $m['expert']]; }
foreach ($agents as $a) {
    $ak = (string) ($a['key'] ?? '');
    if ($ak === '') { continue; }
    $tools = array_sum(array_map('count', (array) ($a['tool_grants'] ?? [])));
    $agentDomain = $pdo->query("SELECT split_part(email, '@', 2) FROM members WHERE member_kind = 'agent' AND email LIKE '%@agents.%' ORDER BY id LIMIT 1")->fetchColumn();
    $agentEmail = ($ak === 'scrum_master' ? 'scrum-master' : $key . '-' . str_replace('_', '-', $ak)) . '@' . ($agentDomain ?: ('agents.' . $domain));
    $hired = find_member_by_email($pdo, $agentEmail);
    if ($hired !== null && !$hire) {
        say('agents', 'done', "{$ak} hired as member {$hired['id']} (" . $hired['display_name'] . ')');
        continue;
    }
    if ($hire) {
        say('agents', 'todo', "hire {$ak} ({$tools} tools, " . count((array) ($a['skills'] ?? [])) . ' skills) — bin/hire_application_agent.php');
        if ($APPLY) {
            $cmd = 'runuser -u www-data -- php ' . escapeshellarg($KERNEL . '/bin/hire_application_agent.php') . ' --app ' . escapeshellarg($key) . ' --agent ' . escapeshellarg($ak) . ' --by ' . escapeshellarg((string) $by['email']) . ' --app-dir ' . escapeshellarg($A);
            [$c, $o] = q($cmd);
            say('agents', $c === 0 ? 'ok' : 'note', str_replace("\n", ' · ', trim($o)));
        }
    } else {
        say('agents', 'note', "proposed: {$ak} — job description {$a['job_description']}, {$tools} tools, " . count((array) ($a['skills'] ?? [])) . " skills. To hire: php bin/hire_application_agent.php --app {$key} --agent {$ak}");
    }
}

// ---- 16. health, and the sign-on proof --------------------------------------------------------------------------------
if ($appId > 0 && $APPLY) {
    $health = check_application_health($pdo, $appId);
    say('health', ($health['status'] ?? '') === 'up' ? 'ok' : 'note', (string) ($health['status'] ?? 'unknown') . (isset($health['endpoints']) ? ': ' . implode(', ', array_map(static fn (array $e): string => $e['name'] . ' ' . $e['status'], $health['endpoints'])) : ''));
    // A real launch as the installer: the hand-off lands (2xx/3xx) and its replay is refused.
    try {
        $appRow = $pdo->query('SELECT * FROM applications WHERE id = ' . $appId)->fetch();
        $member = $pdo->query('SELECT * FROM members WHERE id = ' . $byId)->fetch();
        $launch = sso_launch_url($pdo, $appRow, $member, 'admin', sso_member_holding($pdo, $appId, $byId));
        $ch = curl_init($launch);
        $jar = tempnam(sys_get_temp_dir(), 'sso');
        curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 8, CURLOPT_COOKIEJAR => $jar, CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_RESOLVE => [$fqdn . ':80:127.0.0.1', $fqdn . ':443:127.0.0.1']]);
        curl_exec($ch);
        $first = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_setopt($ch, CURLOPT_COOKIEJAR, tempnam(sys_get_temp_dir(), 'sso'));
        curl_exec($ch);
        $replay = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);
        @unlink($jar);
        $landed = $first >= 200 && $first < 400;
        $refused = $replay >= 400 || $replay === 0;
        say('sign-on', $landed && $refused ? 'ok' : 'note', "hand-off answered {$first}" . ($landed ? ' (landed)' : ' (did not land)') . ", its replay {$replay}" . ($refused ? ' (refused)' : ' (NOT refused)'));
    } catch (Throwable $ex) {
        say('sign-on', 'note', 'could not prove sign-on: ' . $ex->getMessage());
    }
}

// ---- the summary ------------------------------------------------------------------------------------------------------
$todo = count(array_filter($report, static fn (array $r): bool => $r[1] === 'todo'));
$notes = array_filter($report, static fn (array $r): bool => $r[1] === 'note');
echo "\n" . ($APPLY ? 'Applied' : 'Plan') . ": {$todo} step" . ($todo === 1 ? '' : 's') . ($APPLY ? ' were done' : ' to do') . ', ' . count($notes) . ' note' . (count($notes) === 1 ? '' : 's') . ".\n";
echo "The owner's: DNS for {$fqdn}" . ($scheme === 'https' ? ' and its certificate' : ' (and TLS at the proxy)') . "; any grant not named here; hiring or retiring the agents proposed.\n";
echo "Secrets: {$envPath} (group www-data, never printed).\n";
