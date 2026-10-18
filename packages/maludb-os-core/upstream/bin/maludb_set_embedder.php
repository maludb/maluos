<?php
declare(strict_types=1);

/**
 * Give this tenant's MaluDB memory a real embedding model — the owner's decision of 2026-09-19:
 * OpenAI text-embedding-3-small (1536 dimensions, the size the memory already stores, so nothing
 * is re-shaped). Until this runs MaluDB embeds with deterministic hash vectors: who may read what
 * is exact, but ranking inside a result set is arbitrary (docs/build-specs/agent-memory.md).
 *
 *   php bin/maludb_set_embedder.php --key-file /path/to/file-holding-the-openai-key
 *   php bin/maludb_set_embedder.php --check          # say what is configured; change nothing
 *
 * The key is read from a file so it never appears in a command line, a shell history or a log,
 * and it is never printed. It is stored by MaluDB (its provider-key store), not in config/.env.
 * Do this BEFORE memory accumulates: changing the embedder later means re-embedding everything.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/memory/maludb.php';

const EMBED_PROVIDER = 'openai';
const EMBED_MODEL = 'text-embedding-3-small';

$opts = getopt('', ['key-file:', 'check']);

$say = static function (): void {
    $models = maludb_request('GET', '/v1/llm/models');
    $providers = maludb_request('GET', '/v1/llm/providers');
    foreach ($models['body']['models'] ?? [] as $m) {
        if (($m['task'] ?? '') === 'embed') {
            echo 'embed model: ' . (($m['chosen'] ?? false) ? $m['model_name'] . ' (' . ($m['provider'] ?? '?') . ')' : 'not chosen — hash vectors') . "\n";
        }
    }
    $set = array_filter($providers['body']['providers'] ?? [], static fn ($p) => !empty($p['key_set']));
    echo 'provider keys held by MaluDB: ' . (implode(', ', array_column($set, 'provider')) ?: 'none') . "\n";
};

if (isset($opts['check'])) {
    $say();
    exit(0);
}

$file = (string) ($opts['key-file'] ?? '');
if ($file === '' || !is_file($file) || !is_readable($file)) {
    fwrite(STDERR, "Usage: php bin/maludb_set_embedder.php --key-file <file holding the OpenAI API key> | --check\n");
    exit(1);
}
$key = trim((string) file_get_contents($file));
if (!preg_match('/^sk-[A-Za-z0-9_\-]{20,}$/', $key)) {
    fwrite(STDERR, "That file does not hold an OpenAI API key (sk-…).\n");
    exit(1);
}

$r = maludb_request('PUT', '/v1/llm/providers/' . EMBED_PROVIDER, ['api_key' => $key]);
if ($r['status'] < 200 || $r['status'] >= 300) {
    fwrite(STDERR, 'MaluDB refused the provider key: ' . maludb_error($r) . "\n");
    exit(1);
}
$r = maludb_request('PUT', '/v1/llm/models/embed', ['model_name' => EMBED_MODEL]);
if ($r['status'] < 200 || $r['status'] >= 300) {
    fwrite(STDERR, 'MaluDB refused the model choice: ' . maludb_error($r) . "\n");
    exit(1);
}
$say();

// Prove the key works where it matters: one recall, which embeds its query with the new model.
// A bad key shows here, not at an agent's first run.
// (A subject is named because recall with none returns before it embeds anything when the
// query proposes no subject; finding nothing is fine — embedding the query is the test.)
$probe = maludb_request('POST', '/v1/memory/recall',
    ['query' => 'embedding model probe', 'subject' => 'embedding model probe', 'namespaces' => ['org'], 'limit' => 1]);
if ($probe['status'] < 200 || $probe['status'] >= 300) {
    fwrite(STDERR, 'The model is set, but a recall with it failed: ' . maludb_error($probe) . "\nCheck the key, then run this again.\n");
    exit(1);
}
$used = (string) ($probe['body']['embedding_model'] ?? '');
if ($used !== EMBED_MODEL) {
    fwrite(STDERR, 'The model is set, but recall reports embedding with "' . ($used ?: 'nothing') . "\" — not proven.\n");
    exit(1);
}
echo 'recall embedded its query with: ' . $used . "\n";
echo "Done. Delete the key file now: MaluDB holds the key.\n";
