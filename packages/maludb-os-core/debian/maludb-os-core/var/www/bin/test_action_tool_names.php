<?php
declare(strict_types=1);

/**
 * K55's proof (docs/build-specs/kernel-action-tool-names.md): the naming rule on synthetic registries, on COPIES of this
 * installation's registries, and the Actions MCP's own registration (mcp/application_actions.py, run from mcp/venv) over those
 * copies. Reads the live registries and the kernel's action registry; writes only to a temporary directory; touches no database.
 *
 *   php bin/test_action_tool_names.php
 */

require_once dirname(__DIR__) . '/app/features/applications/action_tool_names.php';

$KERNEL = dirname(__DIR__);
$ok = 0;
$fail = 0;
function check(bool $b, string $label): void
{
    global $ok, $fail;
    if ($b) { $ok++; echo "ok    {$label}\n"; } else { $fail++; echo "FAIL  {$label}\n"; }
}
function reg(string $key, array $actions): array
{
    $out = [];
    foreach ($actions as $a) { $out[$a] = ['action' => $a, 'built' => true, 'endpoint' => '/' . $a]; }
    $out['unbuilt_one'] = ['action' => 'unbuilt_one', 'built' => false];
    return ['schema' => 'maludb-os.registry/1', 'app_key' => $key, 'name' => ucfirst($key), 'base_url' => 'http://127.0.0.1:1', 'registry' => ['actions' => $out]];
}
function tools(array $file): array
{
    $m = [];
    foreach (registry_built_actions($file) as $a) { $m[$a['action']] = $a['tool_name'] ?? null; }
    return $m;
}

// ---- the rule ------------------------------------------------------------------------------------------------------------------
$kernel = ['message_send' => true, 'settings_save' => true];
$regs = ['alpha' => reg('alpha', ['customer_create', 'alpha_only', 'settings_save']),
         'beta' => reg('beta', ['customer_create', 'beta_only'])];
[$named, $clashes] = assign_all_tool_names($regs, $kernel);
check($clashes === [], 'no clashes in the synthetic set');
check(tools($named['alpha'])['customer_create'] === 'alpha_customer_create' && tools($named['beta'])['customer_create'] === 'beta_customer_create',
      'a name two applications share takes each application\'s key — no first-come winner');
check(tools($named['alpha'])['alpha_only'] === 'alpha_only' && tools($named['beta'])['beta_only'] === 'beta_only', 'a name one application uses keeps its name');
check(tools($named['alpha'])['settings_save'] === 'alpha_settings_save', 'an application action named like a kernel action takes the prefix; the kernel keeps its name');
check(!isset($named['alpha']['registry']['actions']['unbuilt_one']['tool_name']), 'an unbuilt action is not named');
[$again] = assign_all_tool_names($named, $kernel);
check($again === $named, 'a second run changes nothing');
// a later application sharing a name the incumbent holds alone: the newcomer takes the prefix, the incumbent keeps its name
$gamma = reg('gamma', ['alpha_only', 'gamma_only']);
[$gammaNamed, $c] = assign_registry_tool_names('gamma', $gamma, null, $named, $kernel);
check($c === [] && tools($gammaNamed)['alpha_only'] === 'gamma_alpha_only' && tools($gammaNamed)['gamma_only'] === 'gamma_only',
      'installing a later application never takes a name another holds: it is served as gamma_alpha_only');
$withGamma = $named + ['gamma' => $gammaNamed];
[$alphaAgain] = assign_registry_tool_names('alpha', $regs['alpha'], $named['alpha'], $withGamma, $kernel);
check(tools($alphaAgain) === tools($named['alpha']), 're-installing the incumbent keeps every name it had (its agents\' grants stay right)');
// a prefixed name that would clash, and a name too long
$delta = reg('delta', ['x']);
$epsilon = reg('epsilon', ['delta_x', 'x']);
[$all2, $cl2] = assign_all_tool_names(['delta' => $delta, 'epsilon' => $epsilon], []);
check(isset($cl2['epsilon']['delta_x']) || isset($cl2['delta']['x']), 'a prefixed name that is already another tool\'s is reported, never served twice');
[$long, $cl3] = assign_all_tool_names(['a_very_long_application_key_x' => reg('a_very_long_application_key_x', [str_repeat('y', 40)]),
                                       'z' => reg('z', [str_repeat('y', 40)])], []);
check(isset($cl3['a_very_long_application_key_x']), 'a name longer than 64 characters is reported, not served');

// ---- this installation's registries (copies) ----------------------------------------------------------------------------------
$live = load_action_registries($KERNEL . '/mcp/registries');
$kernelNames = kernel_action_names($KERNEL);
[$liveNamed, $liveClashes] = assign_all_tool_names($live, $kernelNames);
$built = 0;
$names = [];
$dupes = 0;
foreach ($liveNamed as $file) {
    foreach (registry_built_actions($file) as $a) {
        $built++;
        $n = $a['tool_name'] ?? null;
        if ($n === null || isset($names[$n]) || isset($kernelNames[$n])) { $dupes++; }
        $names[(string) $n] = true;
    }
}
check(count($live) > 0 && $liveClashes === [], 'this installation: ' . count($live) . ' registries named without a clash');
check($dupes === 0 && count($names) === $built, "this installation: all {$built} built actions get a name of their own, none a kernel action's");
[$liveAgain] = assign_all_tool_names($liveNamed, $kernelNames);
check($liveAgain === $liveNamed, 'this installation: naming twice changes nothing');
$map = [];
foreach (registry_built_actions($liveNamed['inventory'] ?? reg('inventory', [])) as $a) { $map[$a['action']] = $a['tool_name']; }
check(($map['customer_create'] ?? '') === 'inventory_customer_create', 'Inventory\'s customer_create is served as inventory_customer_create (it was handed the cidery\'s)');

// ---- the Actions MCP's own registration over the named copies ------------------------------------------------------------------
$tmp = sys_get_temp_dir() . '/k55-' . bin2hex(random_bytes(4));
mkdir($tmp . '/registries', 0700, true);
foreach ($liveNamed as $key => $file) {
    file_put_contents($tmp . '/registries/' . $key . '.json', json_encode($file, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
}
$py = <<<'PY'
import json, logging, pathlib, sys
sys.path.insert(0, sys.argv[1] + "/mcp")
import application_actions as aa
aa.REGISTRIES_DIR = pathlib.Path(sys.argv[2])
errors = []
class H(logging.Handler):
    def emit(self, r):
        if r.levelno >= logging.WARNING: errors.append(r.getMessage())
aa.log.addHandler(H())
class FakeMCP:
    def __init__(self): self.names = []
    def add_tool(self, fn, name, description, annotations): self.names.append(name)
kernel = json.load(open(sys.argv[1] + "/mcp/action_registry.json"))
taken = {a["action"] for a in kernel["actions"].values() if a.get("built")}
m = FakeMCP()
n = aa.register(m, None, lambda: "", set(taken))
print(json.dumps({"registered": n, "unique": len(set(m.names)), "errors": errors[:3]}))
PY;
file_put_contents($tmp . '/check.py', $py);
$out = shell_exec(escapeshellarg($KERNEL . '/mcp/venv/bin/python') . ' ' . escapeshellarg($tmp . '/check.py') . ' ' . escapeshellarg($KERNEL) . ' '
    . escapeshellarg($tmp . '/registries') . ' 2>&1');
$res = json_decode(trim((string) $out), true);
check(is_array($res) && $res['registered'] === $built && $res['unique'] === $built && $res['errors'] === [],
      "the Actions MCP's register() serves all {$built} under the new names, with no collision" . (is_array($res) ? '' : ' (said: ' . trim((string) $out) . ')'));
// and an old, unnamed registry beside a named one: never quietly — an error naming the fix
copy($tmp . '/registries/inventory.json', $tmp . '/registries/zz_stale.json');
$stale = json_decode((string) file_get_contents($tmp . '/registries/zz_stale.json'), true);
$stale['app_key'] = 'zz_stale';
foreach ($stale['registry']['actions'] as &$a) { unset($a['tool_name']); }
unset($a);
file_put_contents($tmp . '/registries/zz_stale.json', json_encode($stale));
$out2 = shell_exec(escapeshellarg($KERNEL . '/mcp/venv/bin/python') . ' ' . escapeshellarg($tmp . '/check.py') . ' ' . escapeshellarg($KERNEL) . ' '
    . escapeshellarg($tmp . '/registries') . ' 2>&1');
$res2 = json_decode(trim((string) $out2), true);
check(is_array($res2) && $res2['errors'] !== [] && str_contains((string) $res2['errors'][0], 'actions_tool_names.php'),
      'a registry without tool names that clashes is refused loudly, naming bin/actions_tool_names.php');
array_map('unlink', glob($tmp . '/registries/*') ?: []);
rmdir($tmp . '/registries');
unlink($tmp . '/check.py');
rmdir($tmp);

echo "\n{$ok} ok, {$fail} failed\n";
exit($fail === 0 ? 0 : 1);
