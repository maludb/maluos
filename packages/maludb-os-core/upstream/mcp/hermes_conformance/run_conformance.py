#!/usr/bin/env python3
"""Hermes conformance suite — stage H0 of docs/hermes-integration-plan.md.

Proves, against one installed Hermes Agent release, every seam the Business OS relies on. It is
the upgrade test: bump the Hermes pin, run this, and only then run the evals.

No real model and no platform service is touched. A scripted OpenAI/Anthropic-compatible server
stands where the ledger proxy will stand, a header-logging MCP server (run from the PLATFORM's
venv) stands where records/activity/actions stand, and two logging-only plugins stand where
maludb-hermes and bos_hermes will. Each scenario is one throw-away HERMES_HOME.

    python3 run_conformance.py --hermes /opt/hermes/venv/bin/hermes

The plugins in ./plugins must be pip-installed into that Hermes venv first (see README.md).
Exit status 0 = every REQUIRED check passed. INFO rows record behaviour the design depends on
knowing but does not require (they are compared across upgrades, not asserted).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

KIT = Path(__file__).resolve().parent
LLM_PORT, MCP_PORT = 18080, 18090
PROXY_KEY = "proxy-key-SECRET-bbb222"
RUN_TOKEN = "run-token-SECRET-aaa111"
RUN_ID = "run-42"
M_RECALL, M_CORE = "BOS-RECALLED-FACT-7731", "BOS-CORE-MEMORY-4402"
M_SKILL, M_SOUL = "BOS-SHARED-SKILL-9915", "BOS-SOUL-MARKER-5561"
AUX_TASKS = ("vision compression skills_hub approval review mcp title_generation memory_query_rewrite "
             "tts_audio_tags triage_specifier kanban_decomposer profile_describer goal_judge curator "
             "monitor background_review moa_reference moa_aggregator").split()
ALLOWED_TOOLS = {"mcp__bos__echo_record", "skill_manage", "skill_view", "skills_list", "bos_recall"}
TOOLSETS = "skills,bos,memory"  # the allow-list: skills + the MCP server (bare name) + provider tools

results: list[tuple[str, str, str, str]] = []  # (scenario, level, check, detail)


def record(scenario: str, ok, check: str, detail: str = "", required: bool = True) -> None:
    level = ("PASS" if ok else "FAIL") if required else "INFO"
    results.append((scenario, level, check, detail))


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def render_config(root: Path, *, api: str, transport: str, extra: str = "") -> str:
    aux = "".join(
        f"  {t}:\n    base_url: http://127.0.0.1:{LLM_PORT}/slot/aux-{t}/v1\n"
        f"    api_key: ${{BOS_PROXY_KEY}}\n    model: spike-model\n" for t in AUX_TASKS)
    return f"""model:
  default: spike-model
  provider: custom:bos-ledger
providers:
  bos-ledger:
    api: {api}
    key_env: BOS_PROXY_KEY
    transport: {transport}
    default_model: spike-model
    context_length: 64000
    extra_headers:
      X-BOS-Run-Id: ${{BOS_RUN_ID}}
mcp_servers:
  bos:
    url: http://127.0.0.1:{MCP_PORT}/mcp
    headers:
      Authorization: "Bearer ${{BOS_RUN_TOKEN}}"
      X-BOS-Run-Id: "${{BOS_RUN_ID}}"
    tools:
      include: [echo_record]
      resources: false
      prompts: false
memory:
  memory_enabled: false
  user_profile_enabled: false
  provider: bos-conformance-memory
plugins:
  enabled: [bos-conformance-observer]
skills:
  external_dirs: [{root}/shared-skills]
  create_dir: {root}/outbox
curator:
  enabled: false
updates:
  check: false
tools:
  tool_search:
    enabled: false
auxiliary:
{aux}{extra}"""


class Scenario:
    def __init__(self, work: Path, name: str, args, *, api: str, transport: str = "chat_completions",
                 extra: str = ""):
        self.name, self.args = name, args
        self.root = work / name
        shutil.rmtree(self.root, ignore_errors=True)
        self.home, self.logs = self.root / "home", self.root / "logs"
        for d in (self.home, self.logs, self.root / "outbox", self.root / "cwd",
                  self.root / "shared-skills/ops/bos-shared-skill"):
            d.mkdir(parents=True, exist_ok=True)
        (self.root / "shared-skills/ops/bos-shared-skill/SKILL.md").write_text(
            f"---\nname: bos-shared-skill\ndescription: {M_SKILL} how the organisation files a record\n"
            "version: 1.0.0\n---\n# Filing a record\nStep one: call echo_record.\n", encoding="utf-8")
        (self.home / "SOUL.md").write_text(f"You are the conformance agent. {M_SOUL}\n", encoding="utf-8")
        (self.home / "config.yaml").write_text(render_config(self.root, api=api, transport=transport, extra=extra),
                                               encoding="utf-8")

    def run(self, prompt: str) -> None:
        server_env = {**os.environ, "KIT_LLM_LOG": str(self.logs / "llm.jsonl"),
                      "KIT_MCP_LOG": str(self.logs / "mcp.jsonl"), "KIT_MCP_TOKEN": RUN_TOKEN,
                      "KIT_MARKERS": ",".join((M_RECALL, M_CORE, M_SKILL, M_SOUL))}
        servers = [
            subprocess.Popen([sys.executable, str(KIT / "dummy_llm.py"), str(LLM_PORT)], env=server_env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
            subprocess.Popen([self.args.platform_python, str(KIT / "dummy_mcp.py"), str(MCP_PORT)], env=server_env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
        ]
        try:
            for url in (f"http://127.0.0.1:{LLM_PORT}/slot/probe/v1/models", f"http://127.0.0.1:{MCP_PORT}/mcp"):
                for _ in range(40):
                    try:
                        urllib.request.urlopen(url, timeout=1)
                        break
                    except urllib.error.HTTPError:
                        break  # the MCP endpoint answers 401/406 — it is up
                    except OSError:
                        time.sleep(0.25)
            (self.logs / "llm.jsonl").unlink(missing_ok=True)  # drop the readiness probes
            (self.logs / "mcp.jsonl").unlink(missing_ok=True)
            # A scrubbed environment: the per-run secrets exist ONLY here, never in the profile.
            env = {"PATH": "/usr/bin:/bin", "HOME": str(self.root / "fakehome"), "HERMES_HOME": str(self.home),
                   "KIT_PLUGIN_LOG": str(self.logs / "plugins.jsonl"),
                   "BOS_PROXY_KEY": PROXY_KEY, "BOS_RUN_TOKEN": RUN_TOKEN, "BOS_RUN_ID": RUN_ID}
            proc = subprocess.run(
                [self.args.hermes, "-t", TOOLSETS, "-z", prompt, "--usage-file", str(self.logs / "usage.json")],
                env=env, cwd=self.root / "cwd", capture_output=True, text=True, timeout=self.args.timeout)
            self.exit_code, self.stdout, self.stderr = proc.returncode, proc.stdout, proc.stderr
        finally:
            for s in servers:
                s.terminate()
            for s in servers:
                s.wait(timeout=10)
        self.llm = [r for r in read_jsonl(self.logs / "llm.jsonl") if r["method"] == "POST"]
        self.mcp = read_jsonl(self.logs / "mcp.jsonl")
        self.plugins = read_jsonl(self.logs / "plugins.jsonl")
        try:
            self.usage = json.loads((self.logs / "usage.json").read_text())
        except (OSError, ValueError):
            self.usage = {}

    def events(self, kind: str) -> collections.Counter:
        return collections.Counter(r["event"] for r in self.plugins if r["kind"] == kind)


def tree_hash(path: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(path)).encode() + b"\0" + f.read_bytes())
    return h.hexdigest()


def scenario_base(work: Path, args) -> None:
    n = "base"
    s = Scenario(work, n, args, api=f"http://127.0.0.1:{LLM_PORT}/slot/main/v1")
    shared_before = tree_hash(s.root / "shared-skills")
    skill = ("---\nname: bos-learned-skill\ndescription: How the agent files a record after learning it\n"
             "version: 1.0.0\n---\n# Filing\nUse echo_record with the text.\n")
    s.run("Learn, then file. CALL:skill_manage:" + json.dumps({"action": "create", "name": "bos-learned-skill",
                                                                "content": skill})
          + ' then CALL:echo_record:{"text":"hello from run 42"}')

    record(n, s.usage.get("completed") is True and s.usage.get("failed") is False,
           "headless one-shot completes and writes --usage-file", f"exit={s.exit_code} usage={ {k: s.usage.get(k) for k in ('completed', 'failed', 'api_calls')} }")
    record(n, bool(s.stdout.strip()) and not s.stderr.strip(), "stdout is the answer only; stderr empty",
           f"stderr={s.stderr.strip()[:120]!r}")

    main = [r for r in s.llm if r["slot"] == "main"]
    aux = [r for r in s.llm if r["slot"].startswith("aux-")]
    other = [r for r in s.llm if r["wire"] == "other"]
    record(n, bool(main) and all(r["auth"] == f"Bearer {PROXY_KEY}" for r in main + aux),
           "every model call reaches the proxy position with the per-run key (key_env / ${VAR})",
           f"main={len(main)} aux={len(aux)}")
    record(n, all(r["x_headers"].get("X-BOS-Run-Id") == RUN_ID for r in main),
           "provider extra_headers ${VAR} reaches main-model calls")
    record(n, True, "auxiliary calls carry extra_headers",
           f"{sum(1 for r in aux if r['x_headers'])}/{len(aux)} — correlate runs by proxy KEY, never by header", required=False)
    record(n, True, "auxiliary slots observed at the proxy", ", ".join(sorted({r['slot'] for r in aux})) or "none", required=False)
    record(n, True, "non-inference probes the proxy must answer 404", ", ".join(sorted({r['path'] for r in other})) or "none", required=False)

    offered = set().union(*[set(r["tool_names"]) for r in main]) if main else set()
    record(n, offered == ALLOWED_TOOLS, "tool surface is exactly the allow-list",
           f"extra={sorted(offered - ALLOWED_TOOLS)} missing={sorted(ALLOWED_TOOLS - offered)}")
    record(n, not any("forbidden" in t for t in offered), "MCP tools.include hides an ungranted tool")
    record(n, not ({"memory", "terminal", "delegate_task", "cronjob", "execute_code"} & offered),
           "built-in memory, terminal, delegation, cron and code execution are absent")

    http = [r for r in s.mcp if r["event"] == "http"]
    record(n, bool(http) and all(r["authorization"] == f"Bearer {RUN_TOKEN}" for r in http),
           "every MCP request carries the run token (headers ${VAR})", f"requests={len(http)}")
    record(n, bool(http) and all(r["x_headers"].get("x-bos-run-id") == RUN_ID for r in http),
           "every MCP request carries the run id header")
    record(n, any(r["event"] == "tool" and r["tool"] == "echo_record" for r in s.mcp),
           "Hermes' MCP client executes a tool on the platform's FastMCP build",
           "mcp-protocol-version=" + ",".join(sorted({r["protocol_version"] for r in http if r["protocol_version"]})))
    record(n, "untrusted_tool_result" in s.stdout, "MCP results reach the model wrapped as untrusted data", required=False)

    mem = s.events("memory")
    record(n, all(mem[e] for e in ("initialize", "prefetch", "sync_turn", "on_session_end", "shutdown")),
           "entry-point memory provider loads by name; full lifecycle fires in one-shot",
           " ".join(f"{e}={mem[e]}" for e in ("initialize", "prefetch", "sync_turn", "on_session_end", "shutdown")))
    init = next((r for r in s.plugins if r["kind"] == "memory" and r["event"] == "initialize"), {})
    record(n, {"hermes_home", "agent_identity", "agent_context"} <= set(init.get("kwargs", {})),
           "initialize() receives hermes_home, agent_identity, agent_context", str(init.get("kwargs", {}))[:160])
    agent_calls = [r for r in main if r["n_tools"]]
    record(n, any(r["marker_roles"].get(M_CORE) == ["system"] for r in agent_calls),
           "system_prompt_block (core memory) is in the system prompt")
    record(n, any(M_RECALL and r["markers"].get(M_RECALL) for r in agent_calls),
           "prefetch (recall) text reaches the model",
           "roles=" + str(next((r["marker_roles"][M_RECALL] for r in agent_calls if r["markers"].get(M_RECALL)), [])))
    record(n, any(r["marker_roles"].get(M_SOUL) == ["system"] for r in agent_calls), "SOUL.md is the persona in the system prompt")

    record(n, any(r["marker_roles"].get(M_SKILL) == ["system"] for r in agent_calls),
           "skills.external_dirs skill is indexed in the system prompt")
    record(n, (s.root / "outbox/bos-learned-skill/SKILL.md").exists(), "agent-authored skill lands in skills.create_dir (the outbox)")
    record(n, not list((s.home / "skills").rglob("SKILL.md")), "nothing is written to the profile's own skills dir")
    record(n, tree_hash(s.root / "shared-skills") == shared_before, "the shared skills dir is untouched")

    obs = s.events("observer")
    record(n, obs["pre_api_request"] == obs["post_api_request"] == len(main),
           "observer api hooks fire once per MAIN model call", f"hooks={obs['pre_api_request']} main={len(main)}")
    record(n, True, "model calls invisible to observer hooks (the proxy is the ledger's source)",
           f"{len(s.llm) - len(other) - obs['pre_api_request']} of {len(s.llm) - len(other)}", required=False)
    tool_rows = [r for r in s.plugins if r["kind"] == "observer" and r["event"] == "post_tool_call"]
    record(n, len(tool_rows) == 2 and all(r.get("status") == "ok" for r in tool_rows),
           "observer tool hooks fire once per tool call with status", f"post_tool_call={len(tool_rows)}")
    api_row = next((r for r in s.plugins if r["event"] == "post_api_request"), {})
    record(n, all(api_row.get(k) for k in ("session_id", "turn_id", "api_request_id", "usage"))
           and api_row.get("telemetry_schema_version") == "hermes.observer.v1",
           "observer payloads carry session/turn/api ids, usage and schema v1")
    record(n, obs["on_skill_lifecycle"] >= 1, "on_skill_lifecycle fires when the agent writes a skill")

    leaked = [str(p.relative_to(s.home)) for p in s.home.rglob("*") if p.is_file()
              and any(x.encode() in p.read_bytes() for x in (PROXY_KEY, RUN_TOKEN))]
    record(n, not leaked, "no per-run secret is persisted anywhere under HERMES_HOME", ", ".join(leaked))


def scenario_anthropic(work: Path, args) -> None:
    n = "anthropic"
    s = Scenario(work, n, args, api=f"http://127.0.0.1:{LLM_PORT}/slot/main-anthropic", transport="anthropic_messages")
    s.run('CALL:echo_record:{"text":"anthropic wire"}')
    main = [r for r in s.llm if r["slot"] == "main-anthropic"]
    record(n, bool(main) and all(r["wire"] == "anthropic" and r["path"].endswith("/v1/messages") for r in main),
           "transport anthropic_messages posts native /v1/messages to the custom base", f"calls={len(main)}")
    record(n, all(r["auth"] in (PROXY_KEY, f"Bearer {PROXY_KEY}") for r in main), "the per-run key authenticates it")
    record(n, s.usage.get("completed") is True and any(r["event"] == "tool" for r in s.mcp),
           "tool_use round trip completes on the Anthropic wire")
    record(n, True, "streams", str(sorted({r["stream"] for r in main})), required=False)


def scenario_refusal(work: Path, args) -> None:
    n = "refusal"
    s = Scenario(work, n, args, api=f"http://127.0.0.1:{LLM_PORT}/slot/refuse-main/v1")
    s.run('CALL:echo_record:{"text":"never"}')
    refused = [r for r in s.llm if r["decision"] == "refused"]
    record(n, 1 <= len(refused) <= 2, "a 402 from the proxy is not retried into a storm", f"attempts={len(refused)}")
    record(n, s.usage.get("failed") is True and s.usage.get("completed") is False,
           "--usage-file reports failed=true, completed=false")
    record(n, not any(r["event"] == "tool" for r in s.mcp), "no tool ran")
    record(n, True, "process exit code on a refused run", f"{s.exit_code} — the runner must read --usage-file, not the exit code", required=False)


def scenario_compression(work: Path, args) -> None:
    n = "compression"
    s = Scenario(work, n, args, api=f"http://127.0.0.1:{LLM_PORT}/slot/main/v1",
                 extra="compression:\n  enabled: true\n  checkpoint_required: true\n  threshold_tokens: 3000\n"
                       "  protect_first_n: 1\n  protect_last_n: 4\n")
    filler = "x" * 600
    s.run("Long duty. " + " ".join(f'CALL:echo_record:{{"text":"step {i} {filler}"}}' for i in range(1, 15)))
    slots = collections.Counter(r["slot"] for r in s.llm)
    record(n, slots["aux-compression"] >= 1, "context compression runs through its own auxiliary slot at the proxy", str(dict(slots)))
    pre = [r for r in s.plugins if r["event"] == "on_pre_compress"]
    record(n, bool(pre) and all(r.get("require_checkpoint") is True for r in pre),
           "on_pre_compress (checkpoint API v2) fires with require_checkpoint before the lossy rewrite")
    record(n, s.usage.get("completed") is True, "the run still completes", f"main calls={slots['main']}")
    record(n, True, "background_review fired in a single-turn one-shot",
           str(slots["aux-background_review"] > 0) + " — end-of-run learning belongs to the runner", required=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hermes", required=True, help="path to the hermes executable in the pinned venv")
    ap.add_argument("--platform-python", default=str(KIT.parent / "venv/bin/python"),
                    help="python of the platform MCP venv (runs the dummy MCP server)")
    ap.add_argument("--workdir", default="/tmp/hermes-conformance")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--only", default="", help="comma-separated scenario names")
    ap.add_argument("--json", default="", help="also write the results to this file")
    args = ap.parse_args()

    version = subprocess.run([args.hermes, "--version"], capture_output=True, text=True,
                             env={**os.environ, "HERMES_HOME": str(Path(args.workdir) / "version-home")}).stdout
    print(version.strip().splitlines()[0] if version.strip() else "hermes --version printed nothing")
    work = Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)
    scenarios = {"base": scenario_base, "anthropic": scenario_anthropic, "refusal": scenario_refusal,
                 "compression": scenario_compression}
    wanted = [x for x in args.only.split(",") if x] or list(scenarios)
    for name in wanted:
        try:
            scenarios[name](work, args)
        except Exception as exc:  # a crashed scenario is a failed scenario, not a crashed suite
            record(name, False, "scenario ran", f"{type(exc).__name__}: {exc}")

    width = max(len(c) for _, _, c, _ in results)
    for scenario, level, check, detail in results:
        print(f"{level:4}  {scenario:12} {check:{width}}  {detail}")
    failed = sum(1 for r in results if r[1] == "FAIL")
    print(f"\n{sum(1 for r in results if r[1] == 'PASS')} passed, {failed} failed, "
          f"{sum(1 for r in results if r[1] == 'INFO')} informational")
    if args.json:
        Path(args.json).write_text(json.dumps({"hermes": version.strip(), "results": results}, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
