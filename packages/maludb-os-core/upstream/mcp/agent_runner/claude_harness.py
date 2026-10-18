"""The Claude Agent SDK as a harness — the CLI in print mode, wrapped at a pinned release.

Invocation and outcome are exactly what the conformance suite proved (mcp/claude_conformance):
a one-shot `claude --bare --print --output-format stream-json`; the answer and the outcome come
from the final `result` event, and the events on the way fill agent_run_events without the
observer plugin Hermes needed.

The CLI is used rather than the Python wrapper for one reason: the agent stays a SUBPROCESS we can
sandbox as `bos-agent` with no network beyond localhost. The wrapper would run the loop inside this
service, which holds the provider keys.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
from pathlib import Path

import httpx

from . import claude_launch, claude_render, config, memory
from .harness import Harness, PreparedRun, RunContext, RunOutcome

log = logging.getLogger("agent_runner.claude")

INSTRUCTIONS_PLACEHOLDER = "@bos-instructions-on-stdin@"
STREAM_LINE_LIMIT = 32 * 1024 * 1024       # one stream-json event, a large tool result inside it
MAX_EVENT_BYTES = 4_000_000          # one stream-json line; a huge tool result is in the ledger


class ClaudeAgentHarness(Harness):
    key = "claude_agent_sdk"

    def __init__(self) -> None:
        self._version: str | None = None
        self._running: dict[int, asyncio.subprocess.Process] = {}

    def version(self) -> str:
        """The CLI's own version plus the pinned npm version — an upgrade must be visible in
        agent_runs.sdk_version, because it is what the conformance suite was last run against."""
        if self._version is None:
            out = subprocess.run([config.CLAUDE_BIN, "--version"], capture_output=True, text=True, timeout=60,
                                 env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"})
            cli = (out.stdout.strip().splitlines() or ["claude unknown"])[0]
            pinned = ""
            try:
                pkg = Path(config.CLAUDE_BIN).parents[1] / "node_modules/@anthropic-ai/claude-code/package.json"
                pinned = json.loads(pkg.read_text()).get("version", "")
            except (OSError, ValueError, IndexError):
                pass
            self._version = f"claude-agent-sdk {cli}" + (f" (pinned {pinned})" if pinned else "")
        return self._version

    def prepare(self, context: RunContext) -> PreparedRun:
        agent_dir = config.AGENTS_DIR / str(context.agent["member_id"])
        rendered = claude_render.render(
            context.agent, agent_dir,
            memory_block=memory.persona_block(context.memory.get("core") or {}))
        claude_render.write(agent_dir, rendered)
        return PreparedRun(context=context, profile_dir=agent_dir, profile_hash=rendered["hash"],
                           warnings=rendered["warnings"], detail={"tools": rendered["tools"]})

    async def execute(self, prepared: PreparedRun) -> RunOutcome:
        ctx, agent_dir = prepared.context, prepared.profile_dir
        model = ctx.agent["model"]
        proxy = f"http://127.0.0.1:{config.PROXY_PORT}/anthropic"

        # A scrubbed environment: the two per-run credentials exist here and nowhere on disk. The
        # CLI's Anthropic base URL is the ledger proxy, so every model call is ledgered before it
        # leaves the box — and `--bare` means an API key is the ONLY way it can authenticate. (A model billed to the
        # owner's Claude subscription cannot be `--bare`: claude_launch fences it explicitly instead, and the
        # credential in this environment is STILL only the run's proxy key — the proxy holds the real token.)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(agent_dir / "home"), "LANG": "C.UTF-8",
               "CLAUDE_CONFIG_DIR": str(agent_dir / "config"),
               **claude_launch.auth_env(model, ctx.proxy_key, proxy),
               "BOS_RUN_TOKEN": ctx.run_token, "BOS_PROXY_KEY": ctx.proxy_key,
               "BOS_RUN_ID": str(ctx.run_id), "BOS_RUNNER_URL": f"http://127.0.0.1:{config.API_PORT}",
               "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1", "DISABLE_AUTOUPDATER": "1"}

        # What the agent is asked = the instructions + what shared memory recalled for them.
        # agent_runs keeps the ORIGINAL instructions; the ledger payload shows what was sent.
        asked = memory.instructions_with_recall(ctx.instructions, ctx.memory.get("recalled") or [])
        tools = prepared.detail["tools"]
        command = [config.CLAUDE_BIN, *claude_launch.fence_flags(model), "--print", "--output-format", "stream-json", "--verbose",
                   "--model", model["provider_model_id"],
                   "--system-prompt-file", str(agent_dir / "claude" / "SYSTEM.md"),
                   "--mcp-config", str(agent_dir / "claude" / "mcp.json"), "--strict-mcp-config",
                   "--settings", str(agent_dir / "claude" / "settings.json"),
                   "--plugin-dir", str(agent_dir / "plugin"),
                   "--restricted",
                   "--permission-mode", "dontAsk", "--permission-prompts", "none"]
        # --tools says which tools exist; --allowedTools says which may run WITHOUT a prompt.
        # Without the second every MCP call is denied by the permission mode and the agent reports
        # a day's work it never did (conformance C8). Both lists are the grants, and BOTH ARE
        # ALWAYS PASSED: omitting --tools leaves the CLI's own Edit and Read in the agent's hands,
        # which run 33 showed for an agent with no grants at all. An empty list means no tools —
        # "your tools are the ones you were granted" has to be true of the empty case too.
        # Skills are not a --tools name in --bare mode (the CLI resolves them as /skills:<name> from the
        # --plugin-dir, and the persona carries their text — claude_render, A7 g, 2026-09-22).
        granted = ",".join(tools)
        command += ["--tools", granted, "--allowedTools", granted]
        command += ["--", asked]

        launcher, secrets_in = config.get("RUNNER_AGENT_LAUNCHER"), None
        if launcher:
            # Root-owned wrapper: another unix user, no network beyond localhost (docs/deploy). The
            # credentials go in on STDIN — sudo logs a preserved environment to the journal, and a
            # command line is readable by every local user. The instructions travel the same way.
            secrets_in = ("".join(f"{k}={v}\n" for k, v in env.items())
                          + "BOS_INSTRUCTIONS_B64=" + base64.b64encode(asked.encode()).decode() + "\n").encode()
            command = ["sudo", "-n", launcher, str(agent_dir)] + [INSTRUCTIONS_PLACEHOLDER if c is asked else c
                                                                  for c in command]
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}

        # stream-json is one event per line, and a tool result travels whole inside one: the reader's
        # default 64 KiB line limit failed a run on a single doc page read with skill_read (run 368,
        # "Separator is not found, and chunk exceed the limit"). A line may be as long as a result.
        proc = await asyncio.create_subprocess_exec(
            *command, env=env, cwd=agent_dir / "cwd", stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.PIPE, limit=STREAM_LINE_LIMIT)
        self._running[ctx.run_id] = proc
        if secrets_in:
            proc.stdin.write(secrets_in)
            await proc.stdin.drain()
        proc.stdin.close()

        try:
            result, stderr = await asyncio.wait_for(self._consume(proc, ctx), timeout=ctx.timeout_seconds)
        except asyncio.TimeoutError:
            # An unreachable provider does NOT end the process: the CLI retries past any patience
            # (conformance C8). The harness's own clock is the only one that stops a run.
            proc.kill()
            await proc.wait()
            return RunOutcome("failed", error=f"The run exceeded its {ctx.timeout_seconds}s limit and was stopped.")
        finally:
            self._running.pop(ctx.run_id, None)

        if proc.returncode in (-9, -15, 130):
            return RunOutcome("cancelled", result=(result or {}).get("result"))
        if result is None:
            return RunOutcome("failed", error="The run produced no result event: "
                                              + (stderr.strip()[-600:] or f"exit {proc.returncode}"))
        usage = {"usage": result.get("usage"), "total_cost_usd": result.get("total_cost_usd"),
                 "num_turns": result.get("num_turns"), "session_id": result.get("session_id"),
                 "duration_ms": result.get("duration_ms")}
        # The outcome is read from `result`, NEVER the exit code — the same lesson H0 learned from
        # Hermes. `is_error` is set on a run that streamed cleanly and still failed.
        if result.get("is_error") or result.get("subtype") != "success":
            return RunOutcome("failed", result=None,
                              error=str(result.get("result") or result.get("subtype") or "")[:2000]
                                    or "The run did not complete.",
                              usage_report=usage)
        return RunOutcome("succeeded", result=result.get("result"), usage_report=usage)

    async def _consume(self, proc, ctx: RunContext) -> tuple[dict | None, str]:
        """Read the event stream as it arrives: each line becomes an agent_run_events row through
        the runner's own events endpoint — the same door the Hermes observer plugin knocks on, so
        a run looks identical whichever harness produced it."""
        final: dict | None = None
        pending: dict[str, float] = {}          # tool_use_id -> monotonic start
        async with httpx.AsyncClient(timeout=5.0) as client:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                if len(line) > MAX_EVENT_BYTES or not line.strip().startswith(b"{"):
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "result":
                    final = event
                for row in self._events(event, pending):
                    await self._post(client, ctx, row)
        stderr = (await proc.stderr.read()).decode("utf-8", "replace")
        await proc.wait()
        return final, stderr

    @staticmethod
    def _events(event: dict, pending: dict) -> list[dict]:
        """One stream-json line -> the agent_run_events rows it means. No arguments and no results:
        those are in prompt_payloads, and this table is kept for good."""
        import time
        kind, rows = event.get("type"), []
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        blocks = [b for b in (message.get("content") or []) if isinstance(b, dict)]

        if kind == "system" and event.get("subtype") == "init":
            rows.append({"event": "session_start", "detail": {
                "session_id": event.get("session_id"), "model": event.get("model"),
                "tools": event.get("tools"), "mcp_servers": event.get("mcp_servers"),
                # What the CLI loaded besides tools (A7 g): the skills it will answer to, and plugins.
                "slash_commands": event.get("slash_commands"), "skills": event.get("skills"),
                "plugins": event.get("plugins"), "agents": event.get("agents")}})
        elif kind == "system" and event.get("subtype") == "permission_denied":
            # Never expected: the granted tools are pre-approved. If it happens, the agent was
            # stopped by the platform's own configuration and someone must see it.
            rows.append({"event": "tool_denied", "tool_name": event.get("tool_name"),
                         "tool_call_id": event.get("tool_use_id"), "status": "denied",
                         "error_type": event.get("decision_reason_type"),
                         "error_message": str(event.get("message") or "")[:500]})
        elif kind == "assistant":
            for b in blocks:
                if b.get("type") == "tool_use":
                    pending[b.get("id")] = time.monotonic()
                    rows.append({"event": "tool_call", "tool_name": b.get("name"),
                                 "tool_call_id": b.get("id")})
        elif kind == "user":
            for b in blocks:
                if b.get("type") == "tool_result":
                    started = pending.pop(b.get("tool_use_id"), None)
                    rows.append({"event": "tool_result", "tool_call_id": b.get("tool_use_id"),
                                 "status": "error" if b.get("is_error") else "ok",
                                 "duration_ms": round((time.monotonic() - started) * 1000) if started else None})
        elif kind == "result":
            rows.append({"event": "session_end",
                         "status": "error" if event.get("is_error") else event.get("subtype"),
                         "detail": {"num_turns": event.get("num_turns"),
                                    "duration_ms": event.get("duration_ms"),
                                    "cost_usd": event.get("total_cost_usd")}})
        return rows

    @staticmethod
    async def _post(client: httpx.AsyncClient, ctx: RunContext, row: dict) -> None:
        """Telemetry never breaks a run — the Hermes observer's rule, and this is the same door."""
        try:
            await client.post(f"http://127.0.0.1:{config.API_PORT}/runs/{ctx.run_id}/events",
                              json=row, headers={"Authorization": f"Bearer {ctx.proxy_key}"})
        except Exception as exc:  # noqa: BLE001
            log.warning("run %s: event %s was not reported: %s", ctx.run_id, row.get("event"), exc)

    async def cancel(self, run_id: int) -> None:
        proc = self._running.get(run_id)
        if proc and proc.returncode is None:
            proc.terminate()
