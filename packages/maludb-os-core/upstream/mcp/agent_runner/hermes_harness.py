"""Hermes Agent (Nous Research) as a harness — wrapped at a pinned release, never forked.

Invocation and outcome are exactly what H0 proved (mcp/hermes_conformance): a one-shot
`hermes -t <allow-list> -z <instructions> --usage-file <path>`; stdout is the answer; the outcome
is read from --usage-file because the EXIT CODE IS 0 EVEN WHEN THE RUN FAILED. Hermes' own
scheduler, delegation, gateway and built-in memory stay off: the platform is the organisation.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
from pathlib import Path

from . import config, hermes_render, memory
from .harness import Harness, PreparedRun, RunContext, RunOutcome

INSTRUCTIONS_PLACEHOLDER = "@bos-instructions-on-stdin@"


class HermesHarness(Harness):
    key = "hermes"

    def __init__(self) -> None:
        self._version: str | None = None
        self._aux_tasks: list[str] | None = None
        self._running: dict[int, asyncio.subprocess.Process] = {}

    def _python(self) -> str:
        return str(Path(config.HERMES_BIN).with_name("python"))

    def version(self) -> str:
        if self._version is None:
            out = subprocess.run([config.HERMES_BIN, "--version"], capture_output=True, text=True, timeout=60,
                                 env={"PATH": "/usr/bin:/bin", "HERMES_HOME": str(config.AGENTS_DIR / ".version-home")})
            first = (out.stdout.strip().splitlines() or ["hermes unknown"])[0]
            sha = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(Path(config.HERMES_BIN).parents[2] / "src"), "rev-parse", "--short=8", "HEAD"],
                                 capture_output=True, text=True).stdout.strip()
            self._version = f"{first} {sha}".strip()
        return self._version

    def aux_tasks(self) -> list[str]:
        """Every auxiliary model slot THIS Hermes release has, read from its own defaults — so a
        slot added by an upgrade is pinned to the proxy without anyone remembering to list it."""
        if self._aux_tasks is None:
            code = ("import json;from hermes_cli.config import DEFAULT_CONFIG as D;"
                    "print(json.dumps([k for k,v in D.get('auxiliary',{}).items() if isinstance(v,dict)]))")
            out = subprocess.run([self._python(), "-c", code], capture_output=True, text=True, timeout=120,
                                 env={"PATH": "/usr/bin:/bin", "HERMES_HOME": str(config.AGENTS_DIR / ".version-home")})
            self._aux_tasks = json.loads(out.stdout.strip().splitlines()[-1])
        return self._aux_tasks

    def prepare(self, context: RunContext) -> PreparedRun:
        agent_dir = config.AGENTS_DIR / str(context.agent["member_id"])
        rendered = hermes_render.render(context.agent, self.aux_tasks(), agent_dir,
                                        memory_block=memory.persona_block(context.memory.get("core") or {}))
        hermes_render.write(agent_dir, rendered)
        return PreparedRun(context=context, profile_dir=agent_dir, profile_hash=rendered["hash"],
                           warnings=rendered["warnings"], detail={"toolsets": rendered["toolsets"]})

    async def execute(self, prepared: PreparedRun) -> RunOutcome:
        ctx, agent_dir = prepared.context, prepared.profile_dir
        usage_file = agent_dir / "cwd" / f"usage-{ctx.run_id}.json"
        usage_file.unlink(missing_ok=True)
        # A scrubbed environment: the two per-run credentials exist here and nowhere on disk.
        env = {"PATH": "/usr/bin:/bin", "HOME": str(agent_dir / "home"), "HERMES_HOME": str(agent_dir / "hermes"),
               "BOS_RUN_TOKEN": ctx.run_token, "BOS_PROXY_KEY": ctx.proxy_key, "BOS_RUN_ID": str(ctx.run_id),
               "BOS_RUNNER_URL": f"http://127.0.0.1:{config.API_PORT}", "LANG": "C.UTF-8"}
        # What Hermes is asked = the instructions + what shared memory recalled for them. agent_runs
        # keeps the ORIGINAL instructions; the ledger payload shows exactly what was sent.
        asked = memory.instructions_with_recall(ctx.instructions, ctx.memory.get("recalled") or [])
        command = [config.HERMES_BIN, "-t", ",".join(prepared.detail["toolsets"]), "-z", asked,
                   "--usage-file", str(usage_file)]
        launcher, secrets_in = config.get("RUNNER_AGENT_LAUNCHER"), None
        if launcher:
            # Root-owned wrapper: another unix user, no network beyond localhost (docs/deploy). The
            # credentials go in on STDIN — sudo logs a preserved environment to the journal, and a
            # command line is readable by every local user.
            # The instructions travel the same way: sudo logs its command line too.
            secrets_in = ("".join(f"{k}={v}\n" for k, v in env.items())
                          + "BOS_INSTRUCTIONS_B64=" + base64.b64encode(asked.encode()).decode() + "\n").encode()
            command = ["sudo", "-n", launcher, str(agent_dir)] + [INSTRUCTIONS_PLACEHOLDER if c is asked else c
                                                                  for c in command]
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        proc = await asyncio.create_subprocess_exec(
            *command, env=env, cwd=agent_dir / "cwd", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if secrets_in else asyncio.subprocess.DEVNULL)
        self._running[ctx.run_id] = proc
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(secrets_in), timeout=ctx.timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return RunOutcome("failed", error=f"The run exceeded its {ctx.timeout_seconds}s limit and was stopped.")
        finally:
            self._running.pop(ctx.run_id, None)

        answer = stdout.decode("utf-8", "replace").strip()
        try:
            usage = json.loads(usage_file.read_text())
        except (OSError, ValueError):
            usage = None
        if proc.returncode in (-9, -15, 130):
            return RunOutcome("cancelled", result=answer or None, usage_report=usage)
        if usage is None:
            return RunOutcome("failed", result=answer or None,
                              error="Hermes wrote no usage report: " + (stderr.decode("utf-8", "replace").strip()[-600:] or f"exit {proc.returncode}"))
        if usage.get("failed") or not usage.get("completed"):
            return RunOutcome("failed", result=None, error=answer[:2000] or "The run did not complete.", usage_report=usage)
        return RunOutcome("succeeded", result=answer, usage_report=usage)

    async def cancel(self, run_id: int) -> None:
        proc = self._running.get(run_id)
        if proc and proc.returncode is None:
            proc.terminate()
