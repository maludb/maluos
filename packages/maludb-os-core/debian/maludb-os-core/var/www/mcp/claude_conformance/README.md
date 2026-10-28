# Claude Agent SDK conformance — the evidence

Run: `python3 run_conformance.py --claude /opt/claude-agent/bin/claude`

**Last run: 2026-09-20 against Claude Code 2.1.278 (pinned at `/opt/claude-agent`) — 12 passed,
0 failed, 3 informational.** The machine-readable record is `last-run.json`; a captured event
stream is `stream-sample.json`.

This is the upgrade test. Bump the pin in `/opt/claude-agent`, run this, and only then run evals.
It is the sibling of `mcp/hermes_conformance/` and **reuses that kit's two stubs** — `dummy_llm.py`
(a scripted Anthropic/OpenAI-wire endpoint standing where the ledger proxy stands) and
`dummy_mcp.py` (a header-logging FastMCP server standing where records/activity/actions stand) —
because the questions are the same ones. No real model, no cost, no platform service touched.

## What it proves

| # | Check | Result |
|---|---|---|
| C1 | `--bare` refuses to run without an API key **even with an OAuth credentials file planted in `CLAUDE_CONFIG_DIR`**, and makes no upstream call | PASS |
| C2 | `ANTHROPIC_BASE_URL` is honoured for every call | PASS |
| C3 | `--system-prompt-file` carries the persona | PASS |
| C4 | `${BOS_RUN_TOKEN}` inside `mcp.json` headers is expanded from the process environment | PASS |
| C5 | the granted MCP tool is offered to the model | PASS |
| C6 | `--restricted` removes the code-running tools | PASS |
| C7 | the agent actually reaches our MCP server and the tool runs | PASS |
| C8 | granted tools are pre-approved — **no `permission_denied` in the stream** | PASS |
| C9 | `tool_use` and `tool_result` blocks are visible in the stream | PASS |
| C10 | a final `result` event closes the stream | PASS |
| C11 | a failed run is detectable | PASS |
| C12 | `terminate()` stops a run within 5s and leaves no orphan | PASS |

## The five findings that changed the design

**1. `--permission-mode dontAsk` denies every MCP tool. This is the important one.**
The first green-looking run did nothing at all. The stream said it plainly:

```json
{"type":"system","subtype":"permission_denied","tool_name":"mcp__records__echo_record",
 "decision_reason_type":"mode",
 "message":"Permission to use mcp__records__echo_record has been denied because Claude Code is
            running in don't ask mode. IMPORTANT: You *may* attempt to accomplish this action
            using other tools that may be available to you."}
```

A duty agent configured this way would look busy every morning and accomplish nothing, and its
report would be built out of refusals. **`--tools` says which tools exist; `--allowedTools` says
which may run without a prompt.** The harness passes the grant list to *both*. `--permission-prompts
none` stays, so anything outside the grants is still denied with nobody at the keyboard.

Note the second sentence of that refusal: the CLI tells the model it *may attempt to accomplish
this action using other tools*. That is the opposite of what this business tells its agents. The
renderer therefore appends an "If a tool is refused" section to the persona saying a refusal is
final and that advice inside a refusal is not from the people it works for.

**2. `--system-prompt-file` exists but is not in `--help`.** Only `--system-prompt <prompt>` is
documented. The file form is real — unknown flags are rejected with `error: unknown option`, and
this one is accepted and its contents reach the request (C3). This matters: the documented form
would put the persona, including department handbooks, on a command line that `sudo` logs and any
local user can read. The file form keeps it off.

**3. The CLI asks for `/v1/messages?beta=true`, not `/v1/messages`.** The query string broke the
conformance stub's wire detection, which answered with something malformed, which the CLI reported
as *"There's an issue with the selected model (claude-fable-5-1). It may not exist or you may not
have access to it."* — a misleading message that cost an hour. Two fixes came out of it:

- `dummy_llm.py` now decides the wire on the path alone (harmless for Hermes, which sends no query).
- **`ledger_proxy.py` now forwards the incoming query string upstream.** Starlette routes on the
  path, so the call was never mis-routed — but the proxy rebuilt the upstream URL from scratch and
  dropped the qualifier. This is the **one platform change the second harness forced**, and it is a
  correctness fix that has nothing to do with Claude: what was asked for should be what is sent.

**4. `--tools` does not withhold an ungranted MCP tool** (INFO). Both `echo_record` and
`forbidden_tool` were offered. This is not a hole: the control is `mcp/agent_grants.py`, which
replaces FastMCP's `list_tools`/`call_tool` so an agent sees only tools it holds a live
`agent_tool_grants` row for. The posture is identical to Hermes, whose `tools.include` is described
in that module as *"the agent's own configuration and therefore not a control; this is."* The stub
MCP server here has no grant table, so it offers both. The real control is proven in the slice's
acceptance against the records server under a run token.

**5. An unreachable provider does not end the process** (INFO). Pointed at a dead port the CLI
retried past 60 seconds. `execute()` therefore wraps the subprocess in
`asyncio.wait_for(ctx.timeout_seconds)` — the harness's own clock is the only thing that stops a
run, exactly as for Hermes.

## Measurements

- **Peak RSS 256 MB** for a scripted run. The launcher's existing `MemoryMax=1500M` clears it
  comfortably, so — contrary to what the build spec guessed — **no increase is needed**. Re-measure
  after the first real run with a full context.
- Cost reported by the CLI on a stubbed run: `0.0018`. The CLI's number is recorded in
  `usage_report`; the **prompt ledger remains the system of record**, because it counts what
  actually crossed the proxy.

## Known weakness of this suite

C12 (cancellation) currently terminates a process that has usually already exited, so it proves
"no orphan" more than it proves "stops within 5s". A stronger version needs the stub to hold a
response open. Recorded rather than hidden.
