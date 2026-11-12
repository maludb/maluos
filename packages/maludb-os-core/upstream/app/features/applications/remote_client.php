<?php
declare(strict_types=1);

/**
 * The host half of bin/app_install.php on an application server (MaluOS Phase 14 slice 3; db/194): the calls
 * to the kernel's applications' door, the bundle the kernel's half reads, and the relay vhost through which the
 * kernel reaches this application's internal port. See app/features/applications/remote_install.php.
 */

/** One call to the door under the node token. Answers [HTTP status, decoded JSON or ['raw' => text]]. */
function remote_call(array $remote, string $method, string $path, ?array $body): array
{
    $ch = curl_init($remote['door'] . $path);
    $headers = ['Authorization: Bearer ' . $remote['token'], 'Accept: application/json'];
    $opt = [CURLOPT_RETURNTRANSFER => true, CURLOPT_CONNECTTIMEOUT => 10, CURLOPT_TIMEOUT => 120, CURLOPT_FOLLOWLOCATION => false];
    if ($method === 'POST') {
        $headers[] = 'Content-Type: application/json';
        $opt[CURLOPT_POST] = true;
        $opt[CURLOPT_POSTFIELDS] = json_encode($body ?? new stdClass(), JSON_UNESCAPED_SLASHES);
    }
    $opt[CURLOPT_HTTPHEADER] = $headers;
    curl_setopt_array($ch, $opt);
    $raw = curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $err = curl_error($ch);
    curl_close($ch);
    if ($raw === false) { return [0, ['raw' => $err]]; }
    $json = json_decode((string) $raw, true);
    return [$code, is_array($json) ? $json : ['raw' => mb_substr((string) $raw, 0, 300)]];
}

/** This server's address as the kernel will see it: the source address of a route to the door. */
function remote_own_address(string $door): string
{
    $host = (string) (parse_url($door, PHP_URL_HOST) ?: '');
    $ip = filter_var(trim($host, '[]'), FILTER_VALIDATE_IP) ? trim($host, '[]') : (string) gethostbyname($host);
    exec('ip -o route get ' . escapeshellarg($ip) . ' 2>/dev/null', $out);
    return preg_match('/\bsrc\s+(\S+)/', implode(' ', $out), $mm) === 1 ? $mm[1] : '';
}

/**
 * The files the kernel's half reads, as {path: base64}: the manifest, the action registry and its wrapper, every
 * skill folder the manifest names, the agents' job descriptions (and os/, where they live by convention).
 * Text and small: a file over 512 kB, a dot file and anything that is not a regular file are left out.
 */
function remote_bundle(string $appDir, string $srcDir, array $m): array
{
    $root = is_file($appDir . '/maludb-os.json') ? $appDir : $srcDir;
    $want = ['maludb-os.json', (string) ($m['actions']['registry'] ?? 'mcp/action_registry.json')];
    foreach ((array) ($m['skills'] ?? []) as $rel) { $want[] = (string) $rel; }
    foreach ((array) ($m['agents'] ?? []) as $a) { if (!empty($a['job_description'])) { $want[] = (string) $a['job_description']; } }
    $want[] = 'os';
    foreach (glob($root . '/deploy/kernel-registry*.json') ?: [] as $f) { $want[] = 'deploy/' . basename($f); }
    $files = [];
    $add = static function (string $rel) use (&$files, $root): void {
        $path = $root . '/' . $rel;
        if (is_link($path) || !is_file($path) || filesize($path) > 512 * 1024 || str_starts_with(basename($rel), '.')) { return; }
        $files[$rel] = base64_encode((string) file_get_contents($path));
    };
    foreach (array_unique($want) as $rel) {
        $rel = trim($rel, '/');
        if ($rel === '' || str_contains($rel, '..')) { continue; }
        if (is_dir($root . '/' . $rel)) {
            $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root . '/' . $rel, FilesystemIterator::SKIP_DOTS));
            foreach ($it as $f) {
                $sub = $rel . '/' . ltrim(substr($f->getPathname(), strlen($root . '/' . $rel)), '/');
                if (preg_match('#(^|/)\.#', $sub) !== 1) { $add($sub); }
            }
        } else {
            $add($rel);
        }
    }
    return $files;
}

/**
 * The relay: the application's internal vhost stays on loopback, as its own deploy file wrote it; this vhost
 * listens on this server's address, one port above the range the installer picks from (the internal port + 1000),
 * admits the kernel server's address only, and passes to the internal port. The installer owns the file.
 * Answers ['port' => int, 'state' => 'done'|'todo'|'note', 'detail' => string].
 */
function remote_relay_vhost(string $key, string $address, int $internalPort, string $kernelHost): array
{
    $port = $internalPort + 1000;
    $kernelIp = filter_var(trim($kernelHost, '[]'), FILTER_VALIDATE_IP) ? trim($kernelHost, '[]') : (string) gethostbyname($kernelHost);
    if ($internalPort <= 0 || filter_var($kernelIp, FILTER_VALIDATE_IP) === false) {
        return ['port' => $port, 'state' => 'note', 'detail' => 'no internal port or the kernel\'s address is not known: the kernel cannot post this application\'s actions'];
    }
    $bind = str_contains($address, ':') ? "[{$address}]" : $address;
    $conf = "# written by bin/app_install.php (--kernel): the kernel server posts {$key}'s actions and approval replays here.\n"
        . "# Plain HTTP on the business's network, admitted by address: the kernel server only.\n"
        . "Listen {$bind}:{$port}\n"
        . "<VirtualHost {$bind}:{$port}>\n"
        . "\t<Location />\n\t\tRequire ip {$kernelIp}\n\t</Location>\n"
        . "\tProxyPreserveHost On\n"
        . "\tProxyPass / http://127.0.0.1:{$internalPort}/\n"
        . "\tProxyPassReverse / http://127.0.0.1:{$internalPort}/\n"
        . "\tErrorLog \${APACHE_LOG_DIR}/{$key}-kernel-relay-error.log\n"
        . "\tCustomLog \${APACHE_LOG_DIR}/{$key}-kernel-relay-access.log combined\n"
        . "</VirtualHost>\n";
    $target = "/etc/apache2/sites-available/{$key}-kernel-relay.conf";
    if (is_file($target) && file_get_contents($target) === $conf && is_link("/etc/apache2/sites-enabled/{$key}-kernel-relay.conf")) {
        return ['port' => $port, 'state' => 'done', 'detail' => "{$bind}:{$port} relays the kernel ({$kernelIp}) to the internal port {$internalPort}"];
    }
    if (@file_put_contents($target, $conf) === false) {
        return ['port' => $port, 'state' => 'note', 'detail' => "could not write {$target}"];
    }
    exec('a2enmod -q proxy proxy_http 2>&1; a2ensite -q ' . escapeshellarg("{$key}-kernel-relay") . ' 2>&1 && apachectl configtest 2>&1 && systemctl reload apache2 2>&1', $out, $c);
    return ['port' => $port, 'state' => $c === 0 ? 'todo' : 'note',
            'detail' => $c === 0 ? "{$bind}:{$port} now relays the kernel ({$kernelIp}) to the internal port {$internalPort}" : 'the relay vhost did not load: ' . implode(' ', array_slice($out, -3))];
}
