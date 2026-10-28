<?php
declare(strict_types=1);
/**
 * Proof of the agent directory and delegation, the kernel half of Phase 13 slice 2 (db/190; maluos
 * docs/phase13-slice2-delegation.md): a node registers its agents, the directory and the keys, a desk's task with
 * its envelope stored and leased to the node, the node's result with provenance, every refusal the kernel can see
 * (bad signature, expired, replay, the wrong signer, a bad target), a task that waits for a person and the desk's
 * decision, an operator's action on the node, the lease sweep, the canonical form shared with the hosts' Python,
 * and the directory after the node leaves.
 *
 *   BOS_INTERNAL_URL=http://127.0.0.1:8089 php bin/test_estate_delegation.php
 *
 * Re-runnable; everything it makes is named SMOKE and retired at the end.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/estate/nodes.php';
$pdo = db();
$admin = (int) $pdo->query("SELECT id FROM members WHERE business_role = 'super_admin' AND status = 'active' AND member_kind = 'human' ORDER BY id LIMIT 1")->fetchColumn();
$_SESSION['member_id'] = $admin;
db_apply_context($pdo);
$fails = 0;
$ok = static function (bool $c, string $label) use (&$fails): void { if (!$c) { $fails++; } echo ($c ? '  ok   ' : '  FAIL ') . $label . "\n"; };
$run = date('md-His');
$base = getenv('BOS_INTERNAL_URL') ?: 'http://127.0.0.1:8080';
$call = static function (string $method, string $path, ?string $token, ?array $body = null) use ($base): array {
    $ch = curl_init($base . $path);
    $h = ['Accept: application/json', 'Content-Type: application/json'];
    if ($token !== null) { $h[] = 'Authorization: Bearer ' . $token; }
    curl_setopt_array($ch, [CURLOPT_CUSTOMREQUEST => $method, CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 60, CURLOPT_HTTPHEADER => $h]);
    if ($body !== null) { curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body)); }
    $raw = (string) curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $j = json_decode($raw, true) ?: [];
    return [$code, $j, $j['error']['code'] ?? null];
};
$rpc = static fn (string $path, ?string $token, string $method, array $params = []) => $call('POST', $path, $token, ['jsonrpc' => '2.0', 'id' => 1, 'method' => $method, 'params' => $params]);
$mk = static fn (string $kind = 'server') => desk_code_mint($pdo, $admin, '', $admin, $kind)['code'];
$releaseSmoke = static fn () => $pdo->exec("UPDATE locations SET overlay_address_freed_at = now() - interval '31 days' WHERE name LIKE 'SMOKE %' AND status = 'retired' AND overlay_address_freed_at IS NOT NULL");
$releaseSmoke();
// Re-runnable: what an earlier run left unread in the operator's estate inbox is read now.
$pdo->exec("UPDATE estate_inbox SET status = 'read', read_at = now() WHERE member_id = {$admin} AND status = 'unread'");

// -- keys: a desk's and a node's, made here with libsodium, signed the way the hosts sign
$deskPair = sodium_crypto_sign_keypair(); $deskPub = ssh_ed25519_line(sodium_crypto_sign_publickey($deskPair), 'desk');
$nodePair = sodium_crypto_sign_keypair(); $nodePub = ssh_ed25519_line(sodium_crypto_sign_publickey($nodePair), 'node');
$otherPair = sodium_crypto_sign_keypair();
$sign = static function (array $env, string $keyNode, string $secret): array {
    $env['sender']['node'] = $keyNode;
    $env['sig'] = ['alg' => 'ed25519', 'key' => $keyNode, 'value' => base64_encode(sodium_crypto_sign_detached(envelope_canonical($env), $secret))];
    return $env;
};
$envelope = static function (string $originator, string $onode, string $sender, array $target, string $purpose = 'proof', array $authority = [], array $chain = [], ?array $parent = null): array {
    $now = time();
    $env = ['v' => 1, 'id' => envelope_new_id(), 'issued_at' => gmdate('Y-m-d\TH:i:s\Z', $now), 'expires_at' => gmdate('Y-m-d\TH:i:s\Z', $now + 600), 'nonce' => bin2hex(random_bytes(8)),
            'originator' => ['principal' => $originator, 'kind' => str_starts_with($originator, 'agent:') ? 'agent' : 'human', 'node' => $onode],
            'sender' => ['principal' => $sender, 'node' => $onode],
            'chain' => $chain ?: [['principal' => $sender, 'node' => $onode, 'ts' => gmdate('Y-m-d\TH:i:s\Z', $now), 'task_id' => null]],
            'target' => $target, 'purpose' => $purpose,
            'authority' => $authority ?: ['scopes' => [], 'classification' => 'internal', 'budget' => ['usd' => 0.5, 'calls' => 20]]];
    if ($parent !== null) { $env['parent'] = $parent; }
    return $env;
};

echo "== the canonical form\n";
$sample = ['v' => 1, 'z' => ['b' => 2, 'a' => [3, 1.5, 'x/y', 'é'], 'empty' => [], 'nil' => null], 'id' => 'env_abc', 'sig' => ['value' => 'drop'], 'budget' => ['usd' => 0.5, 'calls' => 20]];
$canon = envelope_canonical($sample);
$ok($canon === '{"budget":{"calls":20,"usd":0.5},"id":"env_abc","v":1,"z":{"a":[3,1.5,"x/y","é"],"b":2}}', 'canonical: sig and empty members dropped, keys sorted, no whitespace, unicode and slashes kept: ' . $canon);
$py = trim((string) shell_exec('printf %s ' . escapeshellarg(json_encode($sample, JSON_UNESCAPED_UNICODE)) . ' | python3 -c ' . escapeshellarg('import json,sys
def c(v):
    if isinstance(v, dict):
        o={}
        for k,x in v.items():
            y=c(x)
            if y is None or y==[] or y=={}: continue
            o[k]=y
        return o
    if isinstance(v, list):
        return [y for y in (c(x) for x in v) if not (y is None or y==[] or y=={})]
    return v
e=json.loads(sys.stdin.read()); e.pop("sig",None)
print(json.dumps(c(e), sort_keys=True, separators=(",",":"), ensure_ascii=False))')));
$ok($py === '' || $py === $canon, 'the hosts\' Python canonicalisation agrees byte for byte' . ($py === '' ? ' (python3 not run)' : ''));

echo "== a node with two agents, a desk with a key\n";
[$st, $j, $e] = $call('POST', '/api/v1/estate/join.php', null, ['surface' => 1, 'kind' => 'server', 'code' => $mk(), 'name' => "SMOKE {$run} node", 'principal' => 'host:smoke', 'hostname' => 'smoke', 'os_platform' => 'linux',
    'os_release' => 'MaluOS 26.04', 'app_version' => 'maluos-estate 0.3.0', 'cpu_cores' => 4, 'memory_mb' => 8000, 'storage_gb' => 100, 'machine_id' => str_repeat(substr(md5('node' . $run), 0, 8), 4), 'public_key' => $nodePub]);
$ok($st === 201 && ($j['node']['id'] ?? 0) > 0, "node joined with its key (#{$j['node']['id']})");
$nodeId = (int) $j['node']['id']; $nodeTok = (string) $j['token']; $nodeRef = "server:{$nodeId}";
$ok(($j['endpoints']['agents'] ?? '') !== '' && ($j['endpoints']['inbox'] ?? '') !== '' && ($j['endpoints']['keys'] ?? '') !== '', 'the join answer names agents, inbox and keys endpoints');
$cd = desk_code_mint($pdo, $admin, '', $admin, 'desk');
[$st, $j, $e] = $call('POST', '/api/v1/desks/enroll.php', null, ['surface' => 1, 'code' => $cd['code'], 'name' => "SMOKE {$run} desk", 'hostname' => 'smoke-desk', 'machine_id' => str_repeat(substr(md5('desk' . $run), 0, 8), 4), 'public_key' => $deskPub]);
$ok($st === 201 && ($j['desk']['id'] ?? 0) > 0, "desk enrolled with its key (#{$j['desk']['id']})");
$deskId = (int) $j['desk']['id']; $deskTok = (string) $j['token']; $deskRef = "desk:{$deskId}";
$ok(($j['endpoints']['agents'] ?? '') !== '' && ($j['endpoints']['inbox'] ?? '') !== '' && ($j['endpoints']['key'] ?? '') !== '' && ($j['endpoints']['actions'] ?? '') !== '', 'the desk answer names agents, inbox, key and (an operator) actions');
$ok((string) $pdo->query("SELECT public_key FROM locations WHERE id = {$deskId}")->fetchColumn() === $deskPub, 'the desk key is on the desk row');
[$st, $j, $e] = $call('POST', '/api/v1/desks/key.php', $deskTok, ['public_key' => 'nope']);
$ok($st === 400 && $e === 'invalid', 'desks/key refuses a key that is not ssh-ed25519');
[$st, $j, $e] = $call('POST', '/api/v1/desks/key.php', $deskTok, ['public_key' => $deskPub]);
$ok($st === 200 && ($j['node'] ?? '') === $deskRef, 'desks/key registers the same key again (idempotent)');

$manifests = [['name' => 'helper', 'display' => 'Helper', 'description' => 'answers through the gateway', 'capabilities' => ['chat', 'Summarise'], 'owner' => 'user:maluos', 'accept_from' => ['org'], 'max_classification' => 'internal', 'tasks' => true],
              ['name' => 'demo', 'description' => 'the demonstration agent', 'capabilities' => ['chat'], 'owner' => 'user:maluos', 'accept_from' => [], 'tasks' => true],
              ['name' => 'Bad Name', 'capabilities' => ['x']]];
[$st, $j, $e] = $call('POST', '/api/v1/estate/agents.php', $nodeTok, ['agents' => $manifests]);
$ok($st === 200 && ($j['registered'] ?? 0) === 2 && count($j['agents'] ?? []) === 2, 'the node registers two agents (a bad name skipped)');
$helper = null; $demo = null;
foreach ($j['agents'] as $a) { if ($a['name'] === 'helper') { $helper = $a; } if ($a['name'] === 'demo') { $demo = $a; } }
$ok($helper !== null && $helper['capabilities'] === ['chat', 'summarise'] && $helper['accept_from'] === ['org'] && $helper['max_classification'] === 'internal' && $helper['node']['ref'] === $nodeRef && $helper['tasks'] !== null, 'helper: tags lowercased, accept_from org, max internal, its node, a task URL');
$ok($demo !== null && $demo['accept_from'] === [] && $demo['owner'] === 'user:maluos', 'demo: accept_from empty (its owner only)');
[$st, $j, $e] = $call('GET', '/api/v1/estate/agents.php?capability=summarise', $deskTok);
$ok($st === 200 && count($j['agents']) === 1 && $j['agents'][0]['name'] === 'helper', 'the directory by capability (a desk token): helper only');
[$st, $j, $e] = $call('GET', "/api/v1/estate/agents.php?node={$nodeId}", $nodeTok);
$ok($st === 200 && count($j['agents']) === 2, 'the directory by node (a node token): both');
[$st, $j, $e] = $call('GET', '/api/v1/desks/agents.php', $deskTok);
$ok($st === 200 && count(array_filter($j['agents'], static fn ($a) => $a['agent'] === 'helper' && $a['tasks'] !== null && $a['node_ref'] === $nodeRef && $a['presence'] === 'online')) === 1, 'desks/agents: the slice 8 shape with the node and a task URL, helper online');
[$st, $j, $e] = $call('GET', '/api/v1/estate/agents.php', null);
$ok($st === 401, 'the directory needs a token');
// the heartbeat registers too, and the report's unit states reach the rows
[$st, $j, $e] = $call('POST', '/api/v1/estate/heartbeat.php', $nodeTok, ['presence' => 'online', 'agents' => $manifests, 'report' => ['ts' => gmdate('c'), 'units' => [], 'agents' => [['name' => 'helper', 'active' => 'active'], ['name' => 'demo', 'active' => 'failed']]]]);
$ok($st === 200 && ($j['agents_registered']['registered'] ?? 0) === 2, 'a heartbeat with the manifest list registers the agents');
[$st, $j, $e] = $call('GET', '/api/v1/estate/agents.php?id=' . $demo['id'], $deskTok);
$ok($st === 200 && $j['agent']['unit_state'] === 'failed' && $j['agent']['state'] === 'failed' && $j['agent']['presence'] === 'offline', 'the report\'s unit state reaches the directory row (demo failed, offline)');

echo "== the keys\n";
[$st, $j, $e] = $call('GET', '/api/v1/estate/keys.php', $nodeTok);
$byNode = []; foreach ($j['keys'] ?? [] as $k) { $byNode[$k['node']] = $k['public_key']; }
$ok($st === 200 && ($byNode[$nodeRef] ?? '') === $nodePub && ($byNode[$deskRef] ?? '') === $deskPub, 'keys: the node\'s and the desk\'s');
$ok(str_starts_with((string) ($j['coordinator']['public_key'] ?? ''), 'ssh-ed25519 ') && ssh_ed25519_raw($j['coordinator']['public_key']) !== null, 'keys: the coordinator\'s, made on first use');
$ok(ssh_ed25519_raw($nodePub) === sodium_crypto_sign_publickey($nodePair), 'ssh-ed25519 lines round-trip to the raw key');
// the coordinator's own signature verifies with the published key
$cenv = envelope_sign_coordinator($pdo, $envelope('coordinator', 'coordinator', 'coordinator', ['agent' => 'helper', 'node' => $nodeRef]));
$ok(sodium_crypto_sign_verify_detached(base64_decode($cenv['sig']['value']), envelope_canonical($cenv), ssh_ed25519_raw($j['coordinator']['public_key'])), 'the coordinator signs and its published key verifies');

echo "== a task from the desk, leased to the node, done with provenance\n";
$tasksUrl = "/api/v1/estate/agents.php?id={$helper['id']}&sub=tasks";
[$st, $j, $e] = $rpc($tasksUrl, $deskTok, 'agent/card');
$ok($st === 200 && ($j['result']['name'] ?? '') === 'Helper' && ($j['result']['node'] ?? '') === $nodeRef && in_array('chat', $j['result']['capabilities'] ?? [], true), 'agent/card from the directory row');
[$st, $j, $e] = $rpc($tasksUrl, $deskTok, 'tasks/send', ['message' => ['role' => 'user', 'parts' => [['type' => 'text', 'text' => 'ping']]], 'wait' => false]);
$ok(($j['error']['data']['reason'] ?? '') === 'envelope_required', 'tasks/send without an envelope: envelope_required');
$env1 = $sign($envelope('user:maluos', $deskRef, 'user:maluos', ['agent' => 'helper', 'node' => $nodeRef], 'ping the helper'), $deskRef, sodium_crypto_sign_secretkey($deskPair));
[$st, $j, $e] = $rpc($tasksUrl, $deskTok, 'tasks/send', ['message' => ['role' => 'user', 'parts' => [['type' => 'text', 'text' => 'ping']]], 'envelope' => $env1, 'wait' => false]);
$task = $j['result'] ?? [];
$ok($st === 200 && ($task['state'] ?? '') === 'queued' && str_starts_with((string) ($task['id'] ?? ''), 't_') && $task['envelope_id'] === $env1['id'] && $task['node'] === $nodeRef && $task['originator'] === 'user:maluos', "tasks/send with a valid envelope: queued ({$task['id']})");
$tid = (string) $task['id'];
[$st, $j, $e] = $rpc($tasksUrl, $deskTok, 'tasks/send', ['message' => ['parts' => [['type' => 'text', 'text' => 'ping']]], 'envelope' => $env1, 'wait' => false]);
$ok(($j['error']['data']['reason'] ?? '') === 'replay', 'the same envelope again: replay');
$ok((int) $pdo->query("SELECT count(*) FROM estate_tasks WHERE envelope_id = '{$env1['id']}'")->fetchColumn() === 1, 'one task row per (envelope, hop)');
$ok((int) $pdo->query("SELECT originator_member_id FROM estate_tasks WHERE id = '{$tid}'")->fetchColumn() === $admin, 'the originator member is the desk\'s owner (bound by the token, not the envelope)');
// the node's inbox
[$st, $j, $e] = $call('GET', '/api/v1/estate/inbox.php?wait=0', $nodeTok);
$item = $j['items'][0] ?? [];
$ok($st === 200 && count($j['items']) === 1 && $item['kind'] === 'task' && $item['id'] === $tid && $item['agent'] === 'helper' && ($item['envelope']['id'] ?? '') === $env1['id'] && ($item['message']['parts'][0]['text'] ?? '') === 'ping' && $item['leases'] === 1, 'the node\'s inbox hands the task with its envelope and message, leased');
[$st, $j, $e] = $call('GET', '/api/v1/estate/inbox.php?wait=0', $nodeTok);
$ok($st === 200 && $j['items'] === [], 'a leased task is not handed out again');
[$st, $j, $e] = $call('GET', '/api/v1/estate/inbox.php?wait=0', $deskTok);
$ok($st === 401, 'a desk token cannot read a node inbox');
[$st, $j, $e] = $rpc($tasksUrl, $deskTok, 'tasks/get', ['id' => $tid]);
$ok($st === 200 && $j['result']['state'] === 'queued', 'tasks/get while leased reads as queued');
$result = ['id' => $tid, 'state' => 'completed', 'output' => ['text' => 'pong', 'artifacts' => []], 'error' => null,
           'provenance' => ['envelope' => $env1['id'], 'node' => $nodeRef, 'agent' => 'agent:helper', 'chain' => array_merge($env1['chain'], [['principal' => 'agent:helper', 'node' => $nodeRef, 'ts' => gmdate('Y-m-d\TH:i:s\Z'), 'task_id' => $tid]]),
                           'models' => [['request' => 'req_1', 'model' => 'mock-7b', 'backend' => 'mock', 'usd' => 0.0]], 'scopes_read' => []],
           'usage' => ['usd' => 0.0, 'calls' => 1, 'budget' => ['usd' => 0.5, 'calls' => 20]]];
[$st, $j, $e] = $call('POST', "/api/v1/estate/inbox.php?id={$tid}&sub=result", $nodeTok, ['result' => $result]);
$ok($st === 200 && ($j['task']['state'] ?? '') === 'completed' && $j['task']['output']['text'] === 'pong', 'the node posts the result: completed');
[$st, $j, $e] = $rpc($tasksUrl, $deskTok, 'tasks/get', ['id' => $tid]);
$t = $j['result'] ?? [];
$ok($st === 200 && $t['state'] === 'completed' && $t['output']['text'] === 'pong' && $t['provenance']['node'] === $nodeRef && $t['provenance']['agent'] === 'agent:helper' && count($t['provenance']['chain']) === 2 && $t['provenance']['models'][0]['model'] === 'mock-7b' && $t['usage']['calls'] === 1 && $t['done_ts'] !== null, 'tasks/get: the result with its provenance (chain of two, one model call) and usage');
[$st, $j, $e] = $call('GET', "/api/v1/estate/tasks.php?id={$tid}", $deskTok);
$ok($st === 200 && $j['task']['id'] === $tid && $j['task']['state'] === 'completed', 'GET estate/tasks/ID as the originator');
[$st, $j, $e] = $call('GET', "/api/v1/estate/tasks.php?id={$tid}", $nodeTok);
$ok($st === 200 && $j['task']['id'] === $tid, 'GET estate/tasks/ID as the agent\'s node');
[$st, $j, $e] = $rpc($tasksUrl, $deskTok, 'tasks/list', ['limit' => 10]);
$ok($st === 200 && count($j['result']['tasks']) === 1 && $j['result']['tasks'][0]['id'] === $tid, 'tasks/list: the desk sees its task');
[$st, $j, $e] = $call('POST', "/api/v1/estate/inbox.php?id={$tid}&sub=result", $nodeTok, ['result' => ['state' => 'failed']]);
$ok($st === 200 && ($j['note'] ?? '') === 'already done' && $j['task']['state'] === 'completed', 'a second result for a done task changes nothing');
// the desk's task interface
[$st, $j, $e] = $rpc("/api/v1/desks/agents.php?id={$helper['id']}&sub=tasks", $deskTok, 'tasks/get', ['id' => $tid]);
$ok($st === 200 && $j['result']['id'] === $tid, 'desks/agents/ID/tasks serves the same interface');
[$st, $j, $e] = $call('GET', "/api/v1/desks/agents.php?id={$helper['id']}&sub=activity", $deskTok);
$ok($st === 200 && count($j['activity']) === 1 && str_contains($j['activity'][0]['summary'], $tid), 'desks/agents/ID/activity lists the task');
// tasks/send by target (capability), with wait=0 so the single-process test server is not held
$env2 = $sign($envelope('user:maluos', $deskRef, 'user:maluos', ['capability' => 'summarise'], 'by capability'), $deskRef, sodium_crypto_sign_secretkey($deskPair));
[$st, $j, $e] = $rpc('/api/v1/estate/tasks.php', $deskTok, 'tasks/send', ['message' => ['parts' => [['type' => 'text', 'text' => 'summarise this']]], 'envelope' => $env2, 'wait' => false]);
$ok($st === 200 && ($j['result']['agent']['name'] ?? '') === 'helper' && $j['result']['state'] === 'queued', 'tasks/send to a capability resolves to helper (demo lacks it and accepts only its owner)');
$tid2 = (string) ($j['result']['id'] ?? '');
$env3 = $sign($envelope('user:maluos', $deskRef, 'user:maluos', ['capability' => 'nothing-does-this']), $deskRef, sodium_crypto_sign_secretkey($deskPair));
[$st, $j, $e] = $rpc('/api/v1/estate/tasks.php', $deskTok, 'tasks/send', ['message' => ['parts' => [['type' => 'text', 'text' => 'x']]], 'envelope' => $env3, 'wait' => false]);
$ok(($j['error']['data']['reason'] ?? '') === 'no_agent', 'a capability nobody has: no_agent');
$env3b = $sign($envelope('user:stranger', $deskRef, 'user:stranger', ['capability' => 'chat']), $deskRef, sodium_crypto_sign_secretkey($deskPair));
$pdo->exec("UPDATE estate_agents SET accept_from = '{user:nobody}' WHERE name = 'helper' AND location_id = {$nodeId}");
[$st, $j, $e] = $rpc('/api/v1/estate/tasks.php', $deskTok, 'tasks/send', ['message' => ['parts' => [['type' => 'text', 'text' => 'x']]], 'envelope' => $env3b, 'wait' => false]);
$ok(($j['error']['data']['reason'] ?? '') === 'no_agent', 'a capability whose holders do not accept the originator: no_agent (accept_from applied at resolution)');
$pdo->exec("UPDATE estate_agents SET accept_from = '{org}' WHERE name = 'helper' AND location_id = {$nodeId}");

echo "== what the kernel refuses\n";
$good = $envelope('user:maluos', $deskRef, 'user:maluos', ['agent' => 'helper', 'node' => $nodeRef]);
$send = static fn (array $env) => $rpc($tasksUrl, $deskTok, 'tasks/send', ['message' => ['parts' => [['type' => 'text', 'text' => 'x']]], 'envelope' => $env, 'wait' => false]);
$tampered = $sign($good, $deskRef, sodium_crypto_sign_secretkey($deskPair)); $tampered['purpose'] = 'changed after signing';
[$st, $j, $e] = $send($tampered);
$ok(($j['error']['data']['reason'] ?? '') === 'bad_signature', 'a tampered envelope: bad_signature');
[$st, $j, $e] = $send($sign($good, $deskRef, sodium_crypto_sign_secretkey($otherPair)));
$ok(($j['error']['data']['reason'] ?? '') === 'bad_signature', 'signed with a key that is not the desk\'s: bad_signature');
[$st, $j, $e] = $send($sign($good, $nodeRef, sodium_crypto_sign_secretkey($nodePair)));
$ok(($j['error']['data']['reason'] ?? '') === 'bad_signature', 'a desk token sending an envelope signed by the node\'s key: bad_signature (the token binds the signer)');
$old = $good; $old['issued_at'] = gmdate('Y-m-d\TH:i:s\Z', time() - 7200); $old['expires_at'] = gmdate('Y-m-d\TH:i:s\Z', time() - 3600);
[$st, $j, $e] = $send($sign($old, $deskRef, sodium_crypto_sign_secretkey($deskPair)));
$ok(($j['error']['data']['reason'] ?? '') === 'expired', 'an expired envelope: expired');
$long = $good; $long['expires_at'] = gmdate('Y-m-d\TH:i:s\Z', time() + 7200);
[$st, $j, $e] = $send($sign($long, $deskRef, sodium_crypto_sign_secretkey($deskPair)));
$ok(($j['error']['data']['reason'] ?? '') === 'bad_envelope', 'a life over an hour: bad_envelope');
$wrong = $good; $wrong['target'] = ['agent' => 'demo', 'node' => $nodeRef]; $wrong['id'] = envelope_new_id(); $wrong['nonce'] = bin2hex(random_bytes(8));
[$st, $j, $e] = $send($sign($wrong, $deskRef, sodium_crypto_sign_secretkey($deskPair)));
$ok(($j['error']['data']['reason'] ?? '') === 'bad_envelope', 'a target that is another agent: bad_envelope');
$nochain = $good; $nochain['chain'] = [['principal' => 'agent:someone-else', 'node' => $deskRef, 'ts' => gmdate('c'), 'task_id' => null]]; $nochain['id'] = envelope_new_id(); $nochain['nonce'] = bin2hex(random_bytes(8));
[$st, $j, $e] = $send($sign($nochain, $deskRef, sodium_crypto_sign_secretkey($deskPair)));
$ok(($j['error']['data']['reason'] ?? '') === 'bad_envelope', 'a chain whose last hop is not the sender: bad_envelope');
$restricted = $good; $restricted['authority']['classification'] = 'secret'; $restricted['id'] = envelope_new_id(); $restricted['nonce'] = bin2hex(random_bytes(8));
[$st, $j, $e] = $send($sign($restricted, $deskRef, sodium_crypto_sign_secretkey($deskPair)));
$ok(($j['error']['data']['reason'] ?? '') === 'bad_envelope', 'an unknown classification: bad_envelope');
// a forwarded envelope: the node's agent forwards the desk's task to demo with a parent
$parent = $sign($envelope('user:maluos', $deskRef, 'user:maluos', ['agent' => 'helper', 'node' => $nodeRef], 'investigate'), $deskRef, sodium_crypto_sign_secretkey($deskPair));
$fwd = $parent; unset($fwd['sig']); $fwd['sender'] = ['principal' => 'agent:helper', 'node' => $nodeRef]; $fwd['target'] = ['agent' => 'demo', 'node' => $nodeRef]; $fwd['nonce'] = bin2hex(random_bytes(8));
$fwd['chain'][] = ['principal' => 'agent:helper', 'node' => $nodeRef, 'ts' => gmdate('Y-m-d\TH:i:s\Z'), 'task_id' => $tid]; $fwd['parent'] = $parent;
$fwd = $sign($fwd, $nodeRef, sodium_crypto_sign_secretkey($nodePair));
[$st, $j, $e] = $rpc("/api/v1/estate/agents.php?id={$demo['id']}&sub=tasks", $nodeTok, 'tasks/send', ['message' => ['parts' => [['type' => 'text', 'text' => 'diagnose']]], 'envelope' => $fwd, 'wait' => false]);
$ok($st === 200 && ($j['result']['state'] ?? '') === 'queued' && $j['result']['hop'] === 2 && $j['result']['originator'] === 'user:maluos' && $j['result']['sender']['principal'] === 'agent:helper', 'a forwarded envelope (hop 2, a parent signed by the desk) from the node: queued, originator kept');
$tid3 = (string) $j['result']['id'];
$fwdBad = $fwd; $fwdBad['parent']['purpose'] = 'tampered parent'; $fwdBad['nonce'] = bin2hex(random_bytes(8)); $fwdBad = $sign($fwdBad, $nodeRef, sodium_crypto_sign_secretkey($nodePair));
[$st, $j, $e] = $rpc("/api/v1/estate/agents.php?id={$demo['id']}&sub=tasks", $nodeTok, 'tasks/send', ['message' => ['parts' => [['type' => 'text', 'text' => 'diagnose']]], 'envelope' => $fwdBad, 'wait' => false]);
$ok(($j['error']['data']['reason'] ?? '') === 'bad_signature', 'a forwarded envelope whose parent was tampered: bad_signature');
$ok((int) $pdo->query("SELECT count(*) FROM estate_nonces WHERE key_node = '{$deskRef}'")->fetchColumn() >= 3, 'nonces are remembered per key');

echo "== a task that waits for the person, and the desk's decision\n";
// the node took tid2 (summarise) and tid3; take them
[$st, $j, $e] = $call('GET', '/api/v1/estate/inbox.php?wait=0', $nodeTok);
$ids = array_column($j['items'], 'id');
$ok(in_array($tid2, $ids, true) && in_array($tid3, $ids, true), 'the node\'s inbox hands the two later tasks');
[$st, $j, $e] = $call('POST', "/api/v1/estate/inbox.php?id={$tid2}&sub=result", $nodeTok,
    ['result' => ['state' => 'pending_approval', 'ask' => ['kind' => 'decision_needed', 'subject' => 'helper asks to run a restricted task', 'body' => 'summarise this (restricted)', 'options' => ['approve', 'deny']]]]);
$ok($st === 200 && ($j['task']['state'] ?? '') === 'pending_approval' && ($j['task']['ask']['subject'] ?? '') !== '', 'the node parks the task: pending_approval with the ask');
[$st, $j, $e] = $call('GET', '/api/v1/desks/inbox.php?wait=0', $deskTok);
$ask = null; foreach ($j['items'] ?? [] as $i) { if ($i['task_id'] === $tid2) { $ask = $i; } }
$ok($st === 200 && $j['unread'] >= 1 && $ask !== null && $ask['kind'] === 'decision_needed' && $ask['from']['principal'] === 'agent:helper' && $ask['from']['node'] === $nodeRef && $ask['options'] === ['approve', 'deny'], 'the desk\'s inbox: decision_needed from helper on the node, unread');
[$st, $j, $e] = $call('POST', '/api/v1/desks/heartbeat.php', $deskTok, ['presence' => 'online']);
$ok($st === 200 && ($j['inbox_unread'] ?? 0) >= 1, 'the desk heartbeat answer carries inbox_unread');
$dec = $envelope('user:maluos', $deskRef, 'user:maluos', ['agent' => 'helper', 'node' => $nodeRef], 'decision');
[$st, $j, $e] = $call('POST', "/api/v1/desks/inbox.php?id={$ask['id']}&sub=decide", $deskTok, ['decision' => 'approve', 'note' => 'go ahead']);
$ok($st === 400 && $e === 'envelope_required', 'a decision without the desk\'s envelope is refused');
[$st, $j, $e] = $call('POST', "/api/v1/desks/inbox.php?id={$ask['id']}&sub=decide", $deskTok, ['decision' => 'maybe', 'envelope' => $sign($dec, $deskRef, sodium_crypto_sign_secretkey($deskPair))]);
$ok($st === 400 && $e === 'invalid', 'a decision outside the options is refused');
$dec['nonce'] = bin2hex(random_bytes(8));
[$st, $j, $e] = $call('POST', "/api/v1/desks/inbox.php?id={$ask['id']}&sub=decide", $deskTok, ['decision' => 'approve', 'note' => 'go ahead', 'envelope' => $sign($dec, $deskRef, sodium_crypto_sign_secretkey($deskPair))]);
$ok($st === 200 && ($j['item']['status'] ?? '') === 'done' && $j['item']['decision'] === 'approve' && ($j['task']['state'] ?? '') === 'queued', 'the decision with the desk\'s envelope: recorded, the task queued again');
[$st, $j, $e] = $call('POST', "/api/v1/desks/inbox.php?id={$ask['id']}&sub=decide", $deskTok, ['decision' => 'deny', 'envelope' => $sign($dec + ['nonce' => bin2hex(random_bytes(8))], $deskRef, sodium_crypto_sign_secretkey($deskPair))]);
$ok($st === 409, 'an item answered twice: conflict');
[$st, $j, $e] = $call('GET', '/api/v1/estate/inbox.php?wait=0', $nodeTok);
$again = null; foreach ($j['items'] as $i) { if ($i['id'] === $tid2) { $again = $i; } }
$ok($again !== null && ($again['answer']['decision'] ?? '') === 'approve' && ($again['answer']['note'] ?? '') === 'go ahead' && ($again['answer']['envelope']['sig']['key'] ?? '') === $deskRef && $again['leases'] === 2, 'the node\'s inbox hands the task again with the signed decision (second lease)');
[$st, $j, $e] = $call('POST', "/api/v1/estate/inbox.php?id={$tid2}&sub=result", $nodeTok, ['result' => ['state' => 'completed', 'output' => ['text' => 'summary'], 'provenance' => ['envelope' => $env2['id'], 'node' => $nodeRef, 'agent' => 'agent:helper'], 'usage' => ['usd' => 0, 'calls' => 1]]]);
$ok($st === 200 && $j['task']['state'] === 'completed' && $j['task']['ask'] === null, 'the released task completes');
[$st, $j, $e] = $call('GET', '/api/v1/desks/inbox.php?wait=0', $deskTok);
$ok($st === 200 && count(array_filter($j['items'], static fn ($i) => $i['task_id'] === $tid2)) === 0, 'the decided item is no longer unread');
// a refusal reaches the originator as fyi
[$st, $j, $e] = $call('POST', "/api/v1/estate/inbox.php?id={$tid3}&sub=result", $nodeTok, ['refused' => 'not_accepted']);
$ok($st === 200 && $j['task']['state'] === 'refused' && $j['task']['reason'] === 'not_accepted', 'the node refuses the forwarded task: refused not_accepted');
[$st, $j, $e] = $call('GET', '/api/v1/desks/inbox.php?wait=0', $deskTok);
$fyi = array_values(array_filter($j['items'], static fn ($i) => $i['task_id'] === $tid3));
$ok(count($fyi) === 1 && $fyi[0]['kind'] === 'fyi' && str_contains($fyi[0]['subject'], 'not_accepted'), 'the originator\'s inbox: an fyi about the refusal');
[$st, $j, $e] = $call('POST', "/api/v1/desks/inbox.php?id={$fyi[0]['id']}&sub=read", $deskTok, []);
$ok($st === 200 && $j['read'] === 1, 'mark read');
[$st, $j, $e] = $call('GET', '/api/v1/desks/inbox.php?wait=0&all=1', $deskTok);
$ok($st === 200 && count($j['items']) >= 2 && $j['unread'] === 0, 'all=1 lists the answered and read items; nothing unread');

echo "== an operator's action on the node\n";
$act = $sign($envelope('user:maluos', $deskRef, 'user:maluos', ['node' => $nodeRef, 'action' => 'restart_agent'], 'restart helper'), $deskRef, sodium_crypto_sign_secretkey($deskPair));
[$st, $j, $e] = $call('POST', "/api/v1/estate/actions.php?node={$nodeId}", $deskTok, ['action' => 'restart_agent', 'agent' => 'helper', 'envelope' => $act]);
$ok($st === 201 && ($j['action']['state'] ?? '') === 'queued' && $j['action']['action'] === 'restart_agent' && $j['action']['agent'] === 'helper', "restart_agent queued ({$j['action']['id']})");
$aid = (string) $j['action']['id'];
[$st, $j, $e] = $call('POST', "/api/v1/estate/actions.php?node={$nodeId}", $deskTok, ['action' => 'format_disk', 'envelope' => $act]);
$ok($st === 400, 'an unknown action is refused');
[$st, $j, $e] = $call('POST', "/api/v1/estate/actions.php?node={$nodeId}", $deskTok, ['action' => 'reboot', 'envelope' => $sign($envelope('user:maluos', $deskRef, 'user:maluos', ['node' => 'server:999999']), $deskRef, sodium_crypto_sign_secretkey($deskPair))]);
$ok($st === 400 && $e === 'bad_envelope', 'an envelope targeting another node is refused');
[$st, $j, $e] = $call('GET', '/api/v1/estate/inbox.php?wait=0', $nodeTok);
$ai = null; foreach ($j['items'] as $i) { if ($i['kind'] === 'action') { $ai = $i; } }
$ok($ai !== null && $ai['id'] === $aid && $ai['action'] === 'restart_agent' && $ai['agent'] === 'helper' && ($ai['envelope']['sig']['key'] ?? '') === $deskRef, 'the node\'s inbox hands the action with the operator\'s envelope');
[$st, $j, $e] = $call('POST', "/api/v1/estate/inbox.php?id={$aid}&sub=result", $nodeTok, ['result' => ['ok' => true, 'output' => 'maluos-agent@helper.service restarted']]);
$ok($st === 200 && $j['action']['state'] === 'completed', 'the node reports the action done');
[$st, $j, $e] = $call('GET', "/api/v1/estate/actions.php?id={$aid}", $deskTok);
$ok($st === 200 && $j['action']['state'] === 'completed' && str_contains((string) ($j['action']['result']['output'] ?? ''), 'restarted'), 'GET actions/ID: completed with the output');
[$st, $j, $e] = $call('GET', '/api/v1/desks/inbox.php?wait=0', $deskTok);
$ok(count(array_filter($j['items'], static fn ($i) => $i['kind'] === 'result' && str_contains($i['subject'], 'restart_agent helper'))) === 1, 'the requester\'s inbox: the action\'s result');
[$st, $j, $e] = $call('GET', '/api/v1/estate/actions.php', $nodeTok);
$ok($st === 200 && count($j['actions']) === 1, 'the node lists its actions');

echo "== leases and the sweep\n";
$env4 = $sign($envelope('user:maluos', $deskRef, 'user:maluos', ['agent' => 'helper', 'node' => $nodeRef]), $deskRef, sodium_crypto_sign_secretkey($deskPair));
[$st, $j, $e] = $rpc($tasksUrl, $deskTok, 'tasks/send', ['message' => ['parts' => [['type' => 'text', 'text' => 'slow']]], 'envelope' => $env4, 'wait' => false]);
$tid4 = (string) $j['result']['id'];
$call('GET', '/api/v1/estate/inbox.php?wait=0', $nodeTok);
$pdo->exec("UPDATE estate_tasks SET lease_until = now() - interval '1 second' WHERE id = '{$tid4}'");
$n = lease_sweep($pdo);
$ok($n === 1 && $pdo->query("SELECT state FROM estate_tasks WHERE id = '{$tid4}'")->fetchColumn() === 'queued', 'an expired lease goes back to the queue');
$pdo->exec("UPDATE estate_tasks SET state = 'leased', leases = 3, lease_until = now() - interval '1 second' WHERE id = '{$tid4}'");
lease_sweep($pdo);
$ok($pdo->query("SELECT state || ':' || reason FROM estate_tasks WHERE id = '{$tid4}'")->fetchColumn() === 'failed:node_unresponsive', 'three leases unanswered: failed node_unresponsive');
$pdo->exec("UPDATE estate_nonces SET expires_at = now() - interval '1 second' WHERE key_node = '{$deskRef}'");
$ok(envelope_nonce_sweep($pdo) >= 3, 'the nonce sweep forgets expired nonces');
$dup = $sign($env1 + ['nonce' => bin2hex(random_bytes(8))], $deskRef, sodium_crypto_sign_secretkey($deskPair));
[$st, $j, $e] = $rpc($tasksUrl, $deskTok, 'tasks/send', ['message' => ['parts' => [['type' => 'text', 'text' => 'ping']]], 'envelope' => $dup, 'wait' => false]);
$ok($st === 200 && ($j['result']['id'] ?? '') === $tid, 'the same envelope id and hop with a fresh nonce returns the existing task (idempotent)');

echo "== settings and the node leaving\n";
$set = present_delegation_for_settings($pdo);
$ok(count(array_filter($set['agents'], static fn ($a) => $a['node']['ref'] === $nodeRef)) === 2 && count($set['tasks']) >= 4 && count($set['actions']) >= 1 && str_starts_with($set['coordinator_key'], 'ssh-ed25519'), 'Settings → Estate: the directory, the tasks, the actions, the coordinator key');
[$st, $j, $e] = $call('POST', '/api/v1/estate/leave.php', $nodeTok);
$ok($st === 200, 'the node leaves');
[$st, $j, $e] = $call('GET', '/api/v1/estate/agents.php', $deskTok);
$ok($st === 200 && count(array_filter($j['agents'], static fn ($a) => $a['node']['ref'] === $nodeRef)) === 0, 'its agents are gone from the directory');
[$st, $j, $e] = $call('GET', '/api/v1/estate/keys.php', $deskTok);
$ok($st === 200 && !in_array($nodeRef, array_column($j['keys'], 'node'), true), 'its key is gone from the keys');
[$st, $j, $e] = $rpc($tasksUrl, $deskTok, 'tasks/send', ['message' => ['parts' => [['type' => 'text', 'text' => 'x']]], 'envelope' => $sign($envelope('user:maluos', $deskRef, 'user:maluos', ['agent' => 'helper', 'node' => $nodeRef]), $deskRef, sodium_crypto_sign_secretkey($deskPair)), 'wait' => false]);
$ok(($j['error']['data']['reason'] ?? '') === 'not_available', 'a task to a removed agent: not_available');

// cleanup
$call('POST', '/api/v1/desks/leave.php', $deskTok);
$pdo->exec("UPDATE locations SET status = 'retired' WHERE name LIKE 'SMOKE {$run} %' AND status = 'active'");
$releaseSmoke();
echo "\n" . ($fails === 0 ? 'PASS' : "FAIL ({$fails})") . "\n";
exit($fails === 0 ? 0 : 1);
