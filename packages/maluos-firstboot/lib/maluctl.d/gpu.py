"""maluctl gpu: the GPUs of this host.

  maluctl gpu status [--json]     every GPU with its driver, memory, load, temperature and power,
                                  the chassis kind and the sharing rule it implies

NVIDIA GPUs are read through nvidia-smi (install the `nvidia` component: sudo apt install
maluos-nvidia); AMD and Intel through /sys/class/drm. Virtual display adapters are not GPUs.
The sharing rule (docs/phase13-shared-gpus.md): a server shares its GPU with the MaluOS
network always, a dedicated desktop when its owner opts in, a laptop when its owner opts in
and only while it is idle; the switch is `maluctl gateway share`. No privileges needed.
"""
import json, sys

sys.path.insert(0, "/usr/lib/maluos")


def main(args):
    import maluos_gpu
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    if args[0] != "status":
        print(__doc__); return 2
    st = maluos_gpu.status()
    if "--json" in args:
        print(json.dumps(st, indent=1)); return 0
    if not st["gpus"]:
        print(f"no GPU on this host (chassis: {st['chassis']}" + ("" if st["nvidia_smi"] else "; nvidia-smi not installed") + ")")
    for g in st["gpus"]:
        print(f"gpu {g['index'] if g['index'] is not None else '-'}:  {maluos_gpu.describe(g)}")
    rule = {"always": "shares always (a server)", "opt-in": "shares when its owner opts in (a dedicated desktop)",
            "opt-in-idle": "shares when its owner opts in, and only while idle (a laptop)"}[st["contribution_rule"]]
    print(f"chassis:  {st['chassis']}  rule: {rule}")
    return 0
