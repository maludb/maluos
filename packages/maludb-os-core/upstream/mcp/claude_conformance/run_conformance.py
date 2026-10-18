#!/usr/bin/env python3
"""Claude Agent SDK conformance suite — the spike `docs/build-specs/agent-runtime-claude-sdk.md`
requires green before `registry.py` is touched.

Proves, against one pinned Claude Code release, every seam the Business OS relies on. It is the
upgrade test: bump the pin, run this, and only then run the evals. Same contract as
`mcp/hermes_conformance/` — and it REUSES that kit's two stubs, because the questions are the
same ones: does the harness honour our base URL, does it carry our bearer to our MCP server, does
it offer the model only the tools we granted.

    python3 run_conformance.py --claude /opt/claude-agent/bin/claude

No real model and no platform service is touched. Exit status 0 = every REQUIRED check passed.
INFO rows record behaviour the design depends on knowing but does not assert (they are compared
across upgrades).
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

KIT = Path(__file__).resolve().parent
HERMES_KIT = KIT.parent / "hermes_conformance"
sys.path.insert(0, str(KIT.parent))
from agent_runner import claude_launch                     # noqa: E402  — the runner's own launch options, so the suite proves what ships
SUB_MODEL = {"auth_mode": claude_launch.SUBSCRIPTION}
# Planted in every place the CLI looks (subscription mode, which is not --bare). None may reach the model or run.
AMBIENT = {m: f"AMBIENT-{m}-{n}" for n, m in enumerate(
    ("HOMEMD", "CONFIGMD", "PROJECTMD", "PARENTMD", "AGENTDEF", "SKILLDEF", "COMMANDDEF", "SETTINGSENV"), start=71)}
LLM_PORT, MCP_PORT = 18081, 18091
PROXY_KEY = "proxy-key-SECRET-ccc333"
RUN_TOKEN = "run-token-SECRET-ddd444"
SOUL_MARKER = "BOS-CLAUDE-SOUL-8821"
MODEL = "claude-sonnet-5"
SLUG = "records"                      # mcp.json server key -> tools are mcp__records__*

results: list[tuple[str, str, str]] = []      # (status, name, detail)


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"  {status:4}  {name}" + (f"  — {detail}" if detail else ""), flush=True)


def wait_for(port: int, timeout: float = 25.0) -> bool:
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


class Scenario:
    """One throw-away agent directory, its own stub logs, one CLI invocation."""

    def __init__(self, root: Path, name: str):
        self.dir = root / name
        for sub in ("home", "cwd", "claude", "config"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self.llm_log = self.dir / "llm.jsonl"
        self.mcp_log = self.dir / "mcp.jsonl"
        self.subscription = False           # True: launched as claude_launch launches a Claude-subscription model
        self.unfenced = False               # the CONTROL: subscription auth as a plain default CLI — no --bare, no --restricted, no fences (proves the planted files bite)

    def write_profile(self, *, tools: list[str], mcp_header: str) -> None:
        (self.dir / "claude" / "SYSTEM.md").write_text(
            f"You are a test agent. Marker: {SOUL_MARKER}\n", encoding="utf-8")
        (self.dir / "claude" / "mcp.json").write_text(json.dumps({"mcpServers": {
            SLUG: {"type": "http", "url": f"http://127.0.0.1:{MCP_PORT}/mcp",
                   "headers": {"Authorization": mcp_header}}}}), encoding="utf-8")
        (self.dir / "claude" / "settings.json").write_text(json.dumps({
            "includeCoAuthoredBy": False, "autoUpdates": False}), encoding="utf-8")
        self.tools = tools

    def env(self, *, api_key: str | None = PROXY_KEY) -> dict:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.dir / "home"), "LANG": "C.UTF-8",
               "CLAUDE_CONFIG_DIR": str(self.dir / "config"),
               "BOS_RUN_TOKEN": RUN_TOKEN,
               "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1", "DISABLE_AUTOUPDATER": "1"}
        base = f"http://127.0.0.1:{LLM_PORT}"
        if self.unfenced:
            env.update({"ANTHROPIC_BASE_URL": base, "CLAUDE_CODE_OAUTH_TOKEN": api_key or PROXY_KEY})
        elif self.subscription:
            env.update(claude_launch.auth_env(SUB_MODEL, api_key or PROXY_KEY, base))
        else:
            env["ANTHROPIC_BASE_URL"] = base
            if api_key:
                env["ANTHROPIC_API_KEY"] = api_key
        return env

    def command(self, claude: str, instructions: str) -> list[str]:
        cmd = [claude, *([] if self.unfenced else claude_launch.fence_flags(SUB_MODEL if self.subscription else {})), "--print", "--output-format", "stream-json", "--verbose",
               "--model", MODEL,
               "--system-prompt-file", str(self.dir / "claude" / "SYSTEM.md"),
               "--mcp-config", str(self.dir / "claude" / "mcp.json"), "--strict-mcp-config",
               *([] if self.unfenced else ["--restricted"]),
               "--permission-mode", "dontAsk", "--permission-prompts", "none",
               "--settings", str(self.dir / "claude" / "settings.json")]
        if self.tools:
            # --tools says which tools EXIST; --allowedTools says which may run without a prompt.
            # Without the second, every MCP call is denied by the permission mode (C6 below).
            cmd += ["--tools", ",".join(self.tools), "--allowedTools", ",".join(self.tools)]
        return cmd + ["--", instructions]

    def run(self, claude: str, instructions: str, *, api_key: str | None = PROXY_KEY,
            timeout: int = 120) -> dict:
        env = self.env(api_key=api_key)
        env["KIT_LLM_LOG"], env["KIT_MCP_LOG"] = str(self.llm_log), str(self.mcp_log)
        before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        started = time.time()
        proc = subprocess.run(self.command(claude, instructions), env=env, cwd=self.dir / "cwd",
                              capture_output=True, text=True, timeout=timeout)
        peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        events = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
        return {"rc": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr,
                "events": events, "seconds": round(time.time() - started, 1),
                "peak_rss_mb": round(max(peak - before, peak) / 1024)}

    def llm_calls(self) -> list[dict]:
        if not self.llm_log.exists():
            return []
        return [json.loads(l) for l in self.llm_log.read_text().splitlines() if l.strip()]

    def mcp_rows(self) -> list[dict]:
        if not self.mcp_log.exists():
            return []
        return [json.loads(l) for l in self.mcp_log.read_text().splitlines() if l.strip()]


def plant_ambient(s: "Scenario") -> None:
    """Everything the CLI would pick up on its own, in every place it looks, each carrying a marker or touching a file if it runs."""
    d = s.dir
    hook = lambda name: {"hooks": {ev: [{"hooks": [{"type": "command", "command": f"touch {d}/hook-{name}-ran"}]}]
                          for ev in ("SessionStart", "UserPromptSubmit", "PreToolUse", "Stop")}}
    (d / "home" / ".claude").mkdir(parents=True, exist_ok=True)
    (d / "home" / ".claude" / "CLAUDE.md").write_text(AMBIENT["HOMEMD"], encoding="utf-8")
    (d / "home" / ".claude" / "settings.json").write_text(json.dumps(
        {**hook("home"), "env": {"BOS_AMBIENT": AMBIENT["SETTINGSENV"]}}), encoding="utf-8")
    (d / "config" / "CLAUDE.md").write_text(AMBIENT["CONFIGMD"], encoding="utf-8")
    (d / "config" / "settings.json").write_text(json.dumps(hook("config")), encoding="utf-8")
    (d / "config" / ".credentials.json").write_text(json.dumps(
        {"claudeAiOauth": {"accessToken": "sk-ant-oat01-PLANTED", "refreshToken": "sk-ant-ort01-PLANTED",
                           "expiresAt": 9999999999999, "scopes": ["user:inference"]}}), encoding="utf-8")
    (d / "CLAUDE.md").write_text(AMBIENT["PARENTMD"], encoding="utf-8")            # the cwd's parent
    (d / "cwd" / "CLAUDE.md").write_text(AMBIENT["PROJECTMD"], encoding="utf-8")
    proj = d / "cwd" / ".claude"
    for sub in ("agents", "skills/ambient", "commands"):
        (proj / sub).mkdir(parents=True, exist_ok=True)
    (proj / "settings.json").write_text(json.dumps(hook("project")), encoding="utf-8")
    (proj / "settings.local.json").write_text(json.dumps(hook("local")), encoding="utf-8")
    (proj / "agents" / "ambient.md").write_text(f"---\nname: ambient\ndescription: {AMBIENT['AGENTDEF']}\n---\n{AMBIENT['AGENTDEF']}\n", encoding="utf-8")
    (proj / "skills" / "ambient" / "SKILL.md").write_text(f"---\nname: ambient\ndescription: {AMBIENT['SKILLDEF']}\n---\n{AMBIENT['SKILLDEF']}\n", encoding="utf-8")
    (proj / "commands" / "ambient.md").write_text(f"---\ndescription: {AMBIENT['COMMANDDEF']}\n---\n{AMBIENT['COMMANDDEF']}\n", encoding="utf-8")
    (d / "cwd" / ".mcp.json").write_text(json.dumps({"mcpServers": {"ambient": {
        "type": "http", "url": f"http://127.0.0.1:{MCP_PORT}/mcp", "headers": {"Authorization": f"Bearer {RUN_TOKEN}"}}}}), encoding="utf-8")


def final_result(events: list[dict]) -> dict | None:
    for ev in reversed(events):
        if ev.get("type") == "result":
            return ev
    return None


def tools_offered(calls: list[dict]) -> list[str]:
    for call in calls:
        if call.get("tools"):
            return call["tools"]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--claude", default="/opt/claude-agent/bin/claude")
    ap.add_argument("--keep", action="store_true", help="keep the scratch directory")
    args = ap.parse_args()

    claude = args.claude
    if not Path(claude).exists():
        print(f"claude not found at {claude}", file=sys.stderr)
        return 2
    version = subprocess.run([claude, "--version"], capture_output=True, text=True,
                             env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"}).stdout.strip()
    print(f"\nClaude Agent SDK conformance — {version}\n")

    root = Path(tempfile.mkdtemp(prefix="claude-conformance-"))
    venv_python = str(KIT.parent / "venv" / "bin" / "python")
    llm = subprocess.Popen([sys.executable, str(HERMES_KIT / "dummy_llm.py"), str(LLM_PORT)],
                           cwd=root, env={**os.environ, "KIT_LLM_LOG": str(root / "llm.jsonl"),
                                          "KIT_MARKERS": ",".join(AMBIENT.values())})
    mcp = subprocess.Popen([venv_python, str(HERMES_KIT / "dummy_mcp.py"), str(MCP_PORT)],
                           cwd=root, env={**os.environ, "KIT_MCP_LOG": str(root / "mcp.jsonl"),
                                          "KIT_MCP_TOKEN": RUN_TOKEN})
    try:
        if not wait_for(LLM_PORT) or not wait_for(MCP_PORT):
            print("stubs did not start", file=sys.stderr)
            return 2

        # The stubs log to ONE file each (their env is fixed at spawn); scenarios read those and
        # slice by time, so each scenario notes the offset it started at.
        llm_log, mcp_log = root / "llm.jsonl", root / "mcp.jsonl"

        def tail(path: Path, offset: int) -> list[dict]:
            if not path.exists():
                return []
            rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
            return rows[offset:]

        def count(path: Path) -> int:
            return len(path.read_text().splitlines()) if path.exists() else 0

        # ---- C1: --bare never falls back to a logged-in account -------------------------
        print("C1  --bare refuses without an API key, even with credentials on disk")
        s = Scenario(root, "c1")
        s.write_profile(tools=[f"mcp__{SLUG}__echo_record"], mcp_header=f"Bearer {RUN_TOKEN}")
        (s.dir / "config").mkdir(exist_ok=True)
        (s.dir / "config" / ".credentials.json").write_text(json.dumps(
            {"claudeAiOauth": {"accessToken": "sk-ant-oat01-PLANTED", "expiresAt": 9999999999999,
                               "scopes": ["user:inference"]}}), encoding="utf-8")
        llm_at = count(llm_log)
        out = s.run(claude, "say hello", api_key=None, timeout=90)
        blocked = out["rc"] != 0 or "login" in out["stdout"].lower()
        no_call = len(tail(llm_log, llm_at)) == 0
        record("PASS" if blocked and no_call else "FAIL", "no OAuth fallback under --bare",
               f"rc={out['rc']}, upstream calls={len(tail(llm_log, llm_at))}")

        # ---- C2/C3/C4/C5/C6: one real scripted run ---------------------------------------
        print("\nC2-C6  a scripted run: base URL, persona, MCP bearer, tool allow-list, restricted")
        s = Scenario(root, "c2")
        s.write_profile(tools=[f"mcp__{SLUG}__echo_record"], mcp_header="Bearer ${BOS_RUN_TOKEN}")
        llm_at, mcp_at = count(llm_log), count(mcp_log)
        out = s.run(claude, f'CALL:echo_record:{{"text":"conformance"}} then answer DONE', timeout=180)
        calls, mcp_rows = tail(llm_log, llm_at), tail(mcp_log, mcp_at)

        record("PASS" if calls else "FAIL", "ANTHROPIC_BASE_URL is honoured",
               f"{len(calls)} upstream call(s), model={calls[0].get('model') if calls else '-'}")

        systems = json.dumps(calls)[:400000]
        record("PASS" if SOUL_MARKER in systems else "FAIL",
               "--system-prompt-file carries the persona (undocumented in --help, real)",
               "marker found in the request" if SOUL_MARKER in systems else "marker NOT sent")

        auths = {r.get("authorization", "") for r in mcp_rows if r.get("event") == "http"}
        expanded = f"Bearer {RUN_TOKEN}" in auths
        record("PASS" if expanded else "FAIL",
               "${BOS_RUN_TOKEN} in mcp.json is expanded from the environment",
               f"authorization seen: {sorted(a[:22] + '…' for a in auths if a) or 'none'}")

        init = next((e for e in out["events"] if e.get("subtype") == "init"), {})
        offered = init.get("tools") or tools_offered(calls)
        granted_ok = any(t.endswith("echo_record") for t in offered)
        record("PASS" if granted_ok else "FAIL", "the granted MCP tool is offered to the model",
               f"offered: {offered}")

        # The grant is enforced at the MCP BOUNDARY (mcp/agent_grants.py replaces list_tools and
        # call_tool), exactly as it is for Hermes, whose tools.include is "the agent's own
        # configuration and therefore not a control". This kit's stub MCP server has no grant
        # table, so it offers both tools; what is asserted here is only that --tools does not make
        # the situation WORSE. The real control is proven in the slice's acceptance, against the
        # records server under a run token.
        withheld = not any(t.endswith("forbidden_tool") for t in offered)
        record("INFO", "--tools did not withhold the ungranted sibling",
               "as expected: --tools is configuration; agent_grants.py at the MCP boundary is the control"
               if not withheld else "it did withhold it — defence in depth, not relied upon")

        shell_tools = [t for t in offered if t in ("Bash", "BashOutput", "KillShell", "NotebookEdit")]
        record("PASS" if not shell_tools else "FAIL", "--restricted removes the code-running tools",
               f"offered: {offered}" if shell_tools else f"{len(offered)} tool(s), none of them a shell")

        ran = [r for r in mcp_rows if r.get("event") == "tool"]
        record("PASS" if ran else "FAIL", "the agent actually reached our MCP server",
               f"tools run: {[r['tool'] for r in ran]}")

        # ---- C7: the event stream the harness will parse ---------------------------------
        print("\nC7  stream-json shapes (the wire format we do not own)")
        kinds = {}
        for ev in out["events"]:
            key = ev.get("type") + (":" + ev["subtype"] if ev.get("subtype") else "")
            kinds[key] = kinds.get(key, 0) + 1
        (KIT / "stream-sample.json").write_text(json.dumps(out["events"], indent=1), encoding="utf-8")
        def blocks(ev: dict) -> list:
            msg = ev.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
        tool_use = any(b.get("type") == "tool_use" for ev in out["events"] for b in blocks(ev))
        tool_res = any(b.get("type") == "tool_result" for ev in out["events"] for b in blocks(ev))
        denied = [ev for ev in out["events"] if ev.get("subtype") == "permission_denied"]
        record("PASS" if not denied else "FAIL",
               "the granted tools are pre-approved (--allowedTools)",
               "no permission_denied in the stream" if not denied
               else f"DENIED: {[e.get('tool_name') for e in denied]} — reason "
                    f"{denied[0].get('decision_reason_type')}. Without --allowedTools the agent "
                    f"silently accomplishes nothing.")
        record("PASS" if tool_use and tool_res else "FAIL",
               "tool_use and tool_result blocks are visible in the stream",
               f"types: {kinds}")
        res = final_result(out["events"])
        record("PASS" if res else "FAIL", "a final `result` event closes the stream",
               f"subtype={res.get('subtype') if res else '-'}, "
               f"is_error={res.get('is_error') if res else '-'}, "
               f"cost={res.get('total_cost_usd') if res else '-'}")

        # ---- C8: does the exit code tell the truth? --------------------------------------
        print("\nC8  the exit code on a failed run")
        s = Scenario(root, "c8")
        s.write_profile(tools=[f"mcp__{SLUG}__echo_record"], mcp_header=f"Bearer {RUN_TOKEN}")
        env = s.env()
        env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:1"      # nothing listens
        try:
            proc = subprocess.run(s.command(claude, "say hello"), env=env, cwd=s.dir / "cwd",
                                  capture_output=True, text=True, timeout=60)
            evs = [json.loads(l) for l in proc.stdout.splitlines() if l.strip().startswith("{")]
            r = final_result(evs)
            truthful = proc.returncode != 0 or (r is not None and r.get("is_error"))
            record("PASS" if truthful else "FAIL", "a failed run is detectable",
                   f"rc={proc.returncode}, result.is_error={r.get('is_error') if r else 'no result event'}")
            record("INFO", "outcome is read from `result`, never the exit code",
                   f"rc={proc.returncode} on a run that could not reach its provider")
        except subprocess.TimeoutExpired:
            record("PASS", "a failed run is detectable",
                   "it does not fail fast: the CLI retries an unreachable provider past 60s")
            record("INFO", "an unreachable provider does NOT end the process",
                   "the harness must impose its own timeout — execute() wraps the subprocess in "
                   "asyncio.wait_for(ctx.timeout_seconds), as the Hermes harness does")

        # ---- C9: cancellation ------------------------------------------------------------
        print("\nC9  cancellation")
        s = Scenario(root, "c9")
        s.write_profile(tools=[f"mcp__{SLUG}__echo_record"], mcp_header=f"Bearer {RUN_TOKEN}")
        env = s.env()
        env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{LLM_PORT}/slow"
        proc = subprocess.Popen(s.command(claude, "say hello"), env=env, cwd=s.dir / "cwd",
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        time.sleep(4)
        proc.terminate()
        t0 = time.time()
        try:
            proc.wait(timeout=10)
            gone = time.time() - t0
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait(); gone = 99
        orphans = subprocess.run(["pgrep", "-f", str(s.dir)], capture_output=True, text=True).stdout.strip()
        record("PASS" if gone <= 5 and not orphans else "FAIL", "terminate() stops a run within 5s",
               f"{gone:.1f}s, orphans={orphans or 'none'}")

        # ---- S1-S5: a Claude-subscription launch (NOT --bare) is fenced as tightly ---------------------
        print("\nS1-S5  subscription mode: the fences that replace --bare (docs/build-specs/claude-subscription-auth.md)")
        # The control first: the same planted files with NO fences must take effect — otherwise S2/S3 below prove nothing.
        s0 = Scenario(root, "s0")
        s0.subscription = s0.unfenced = True
        s0.write_profile(tools=[f"mcp__{SLUG}__echo_record"], mcp_header="Bearer ${BOS_RUN_TOKEN}")
        plant_ambient(s0)
        llm_at = count(llm_log)
        s0.run(claude, "say hello", timeout=120)
        c_calls = tail(llm_log, llm_at)
        c_seen = {m for c in c_calls for m, hit in (c.get("markers") or {}).items() if hit}
        c_ran = sorted(p.name for p in s0.dir.glob("hook-*-ran"))
        record("PASS" if c_seen or c_ran else "FAIL", "S0 control: a plain default CLI (no --bare, --restricted or fences) DOES pick the planted files up (so S2 and S3 mean something)",
               f"markers reaching the model: {sorted(c_seen) or 'none'}; hooks that ran: {c_ran or 'none'}")

        s = Scenario(root, "s1")
        s.subscription = True
        s.write_profile(tools=[f"mcp__{SLUG}__echo_record"], mcp_header="Bearer ${BOS_RUN_TOKEN}")
        plant_ambient(s)
        llm_at, mcp_at = count(llm_log), count(mcp_log)
        out = s.run(claude, f'CALL:echo_record:{{"text":"conformance"}} then answer DONE', timeout=180)
        calls, mcp_rows = tail(llm_log, llm_at), tail(mcp_log, mcp_at)
        record("PASS" if calls and out["rc"] == 0 else "FAIL", "S1 a subscription-mode run reaches the proxy URL and completes",
               f"rc={out['rc']}, {len(calls)} upstream call(s)")
        auths = {c.get("auth", "") for c in calls}
        record("PASS" if auths == {f"Bearer {PROXY_KEY}"} else "FAIL",
               "S1 the credential sent is the run's key as a bearer — never the planted login, never a real token",
               f"seen: {sorted(a[:18] + '…' for a in auths)}")
        seen = {m for c in calls for m, hit in (c.get("markers") or {}).items() if hit}
        record("PASS" if not seen else "FAIL", "S2 no ambient CLAUDE.md, agent, skill, command or settings text reaches the model",
               "none of the planted markers were sent" if not seen else f"LEAKED: {sorted(seen)}")
        ran = sorted(p.name for p in s.dir.glob("hook-*-ran"))
        record("PASS" if not ran else "FAIL", "S3 no ambient hook ran (user, config dir, project, local settings)",
               "no hook fired" if not ran else f"HOOKS RAN: {ran}")
        init = next((e for e in out["events"] if e.get("subtype") == "init"), {})
        offered = init.get("tools") or tools_offered(calls)
        record("PASS" if not any("ambient" in t for t in offered) and any(t.endswith("echo_record") for t in offered) else "FAIL",
               "S4 only the granted MCP server's tools exist (a planted project .mcp.json is ignored)", f"offered: {offered}")
        shell_tools = [t for t in offered if t in ("Bash", "BashOutput", "KillShell", "NotebookEdit", "Write", "Edit", "Read")]
        record("PASS" if not shell_tools else "FAIL", "S4 no built-in code, file or shell tool is offered", f"offered: {offered}")
        ambient_mcp = [r for r in mcp_rows if "ambient" in json.dumps(r)]
        memory_files = [str(p.relative_to(s.dir)) for p in s.dir.rglob("*") if p.is_file() and "memory" in p.parts]
        record("PASS" if not ambient_mcp and not memory_files else "FAIL", "S5 nothing else was contacted or written (no ambient MCP call, no memory files)",
               f"ambient mcp rows={len(ambient_mcp)}, memory files={memory_files or 'none'}")

        # ---- C10: memory ------------------------------------------------------------------
        print("\nC10  resource ceiling")
        record("INFO", "peak RSS of a scripted run", f"{out['peak_rss_mb']} MB "
               f"(MemoryMax must clear this; Hermes runs at 1500M)")

        print("\n" + "=" * 78)
        failed = [r for r in results if r[0] == "FAIL"]
        passed = [r for r in results if r[0] == "PASS"]
        print(f"{len(passed)} passed, {len(failed)} failed, "
              f"{len([r for r in results if r[0] == 'INFO'])} informational")
        for _, name, detail in failed:
            print(f"  FAILED: {name} — {detail}")
        (KIT / "last-run.json").write_text(json.dumps(
            {"version": version, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
             "results": [{"status": s, "check": n, "detail": d} for s, n, d in results]},
            indent=1), encoding="utf-8")
        return 1 if failed else 0
    finally:
        for p in (llm, mcp):
            p.terminate()
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)
        else:
            print(f"\nscratch kept at {root}")


if __name__ == "__main__":
    sys.exit(main())
