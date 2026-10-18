# Build spec: the Claude Agent SDK harness — the second harness

> **Status: BUILT 2026-09-20.** Evidence: `mcp/claude_conformance/README.md` (12 passed, 0 failed,
> 3 informational, against Claude Code 2.1.278 pinned at `/opt/claude-agent`). Install:
> `docs/deploy/claude-agent-install.md`. What the spike changed in this spec is marked
> **[spike]** below. No schema change: `model_registry.harness` has admitted `claude_agent_sdk`
> since `db/042` and three agents were already hired on it.
>
> Owner's decision, 2026-09-20: **Claude Agent SDK only** — not the OpenAI Agents SDK, not the
> OpenAI-compatible-local harness. A second harness is what proves the interface generalises; a third
> proves less per unit of work, and neither of the other two has an agent hired on it.

This slice is build-plan **phase 5, step 1**, the half of it that is not built: *"Claude Agent SDK,
OpenAI Agents SDK and OpenAI-compatible-local harnesses prove the registry generalizes."*

## Why it is urgent, not merely owed

Three agents are `active`, hired on 2026-09-18, and **cannot run**:

| member | name | job title | model | harness | runs |
|---|---|---|---|---|---|
| 38 | Johnathan | IT Director | `claude-fable-5-1` | `claude_agent_sdk` | 0 |
| 40 | Claude | Software Engineer | `claude-fable-5-1` | `claude_agent_sdk` | 0 |
| 41 | Audi | Audit Department Manager | `claude-fable-5-1` | `claude_agent_sdk` | 0 |

`registry.get()` registers exactly `(HermesHarness,)`, so every one of these raises
`LookupError("No harness is built for 'claude_agent_sdk' yet")` — at dispatch, after the hire, after
the roster has shown them as working agents for two days. The roster is telling the owner something
untrue. This slice makes it true.

## Sources this spec may never contradict

`docs/build-specs/agent-runtime-hermes.md` (the runner owns a run's life; a harness only prepares and
executes) · `docs/build-specs/agent-hr.md` (config versions are immutable; agents never administer) ·
`docs/build-specs/agent-memory.md` · `docs/build-specs/agent-skills.md` · `CLAUDE.md` "Agent decisions
already made" — in particular **API keys only: no claude.ai/Pro/Max login in the product**, because the
Agent SDK terms require prior Anthropic approval for that.

## What this slice is — and is not

**Is:** one class implementing `Harness` (`mcp/agent_runner/harness.py`), one entry in
`registry.py`, a profile renderer beside `hermes_render.py`, a pinned root-owned install of the
Claude Code CLI, the sandbox launcher extended to admit its binary, and a conformance suite that
proves every claim below on this host before a single agent is pointed at it.

**Is not:** a schema change · a screen · the eval runner (its own slice) · the OpenAI Agents SDK
or OpenAI-compatible harnesses (declined above) · any change to how the ledger proxy, run token,
MCP servers, memory, skills or approvals work — the whole point is that **a harness plugs into the
runner without the platform noticing**, and if this slice needs to change the platform, the
interface was wrong and that is the finding.

## The shape of the thing (and why it mirrors Hermes)

The Claude Agent SDK is the Claude Code CLI plus language wrappers. Using the **CLI in print mode**
rather than the Python wrapper is deliberate, and it is the same choice H0 made for Hermes:

- The agent process stays a **subprocess we can sandbox**. The Python SDK would run the loop inside
  `maludb-os-agent-runner`, which holds the provider API keys and has full network. A subprocess runs
  as `bos-agent` under `systemd-run` with `IPAddressDeny=any` + `IPAddressAllow=localhost`, exactly as
  Hermes does, and cannot reach a provider even if it tried.
- `--print --output-format stream-json` emits tool-call events natively, so `agent_run_events` (db/122)
  is filled **without** the observer plugin Hermes needed.
- One-shot invocation matches `Harness.execute()` exactly: instructions in, answer out, outcome read
  from the final `result` event.

### The invocation

```
claude --bare --print --output-format stream-json --verbose
       --model <model_registry.provider_model_id>
       --system-prompt-file <agent_dir>/claude/SYSTEM.md
       --mcp-config <agent_dir>/claude/mcp.json --strict-mcp-config
       --restricted --tools <granted tool names>
       --permission-mode dontAsk --permission-prompts none
       --settings <agent_dir>/claude/settings.json
       -- <instructions + recalled memory>
```

Each flag earns its place, and the conformance suite proves each one:

| Flag | Why it is not optional |
|---|---|
| `--bare` | *"Anthropic auth is strictly `ANTHROPIC_API_KEY` or `apiKeyHelper` — OAuth and keychain are never read."* This is CLAUDE.md's API-keys-only rule enforced by the binary rather than by our good intentions. It also skips hooks, plugins, LSP, auto-memory and `CLAUDE.md` auto-discovery — every one of which would put text into the agent that the platform did not put there. |
| `--strict-mcp-config` | Only the servers we wrote in `mcp.json`. Without it the CLI may merge user/project MCP configuration from the filesystem. |
| `--restricted` | Removes Bash, the code-running tools and WebFetch unless `--tools` names them, and **ignores user, project and local settings files**. An office agent reaches the business through MCP tools; it does not run shell commands on the office VM. |
| `--tools` | The allow-list *is* `agent_tool_grants`, rendered. A tool the agent was not granted is not on the command line. |
| `--permission-prompts none` | Anything that would prompt is denied automatically. There is nobody at the keyboard at 07:00. |
| `--allowedTools` **[spike]** | `--tools` says which tools *exist*; this says which may run *without a prompt*. Without it the permission mode denies **every** MCP call and the agent reports a morning's work it never did. Both lists are the grants. |
| `--tools` is passed even when EMPTY **[spike]** | Omitting it leaves the CLI's own `Edit` and `Read` in a grantless agent's hands — run 33 showed exactly that. `--tools ""` yields zero tools. "Your tools are the ones you were granted" has to hold for the empty case too. |
| `--print … stream-json` | The events are the telemetry; see below. |

`ANTHROPIC_BASE_URL` points at the run's ledger proxy and `ANTHROPIC_API_KEY` is the run's proxy key
(`RunContext.proxy_key`), so **every model call this agent makes is already ledgered** by the
machinery the Hermes harness proved — nothing in the prompt ledger changes for this slice.

### What `prepare()` renders — `mcp/agent_runner/claude_render.py`

Deterministic, like `hermes_render.render()`: the same config version renders the same bytes and
`sha256` of them is `agent_runs.profile_hash`.

| File in `<agent_dir>/claude/` | Contents |
|---|---|
| `SYSTEM.md` | The persona: the shared preamble, the job description, the department handbooks. **Byte-identical in substance to what Hermes gets** — see "One persona, two harnesses" below. |
| `mcp.json` | One `{"type": "http", "url": …, "headers": {"Authorization": "Bearer ${BOS_RUN_TOKEN}"}}` per platform endpoint in `agent["endpoints"]`, keyed by `hermes_render.server_slug(name)` so **a tool has the same name under both harnesses** (`mcp__records__find_contacts`). External endpoints are skipped with the same warning Hermes gives. |
| `settings.json` | `includeCoAuthoredBy: false`, telemetry off, no auto-update, no analytics. Managed settings only; `--restricted` already ignores the rest. |

`profile_hash = sha256(system_prompt + "\0" + mcp_config + "\0" + settings + "\0" + ",".join(tools))`.
Core memory is appended to `SYSTEM.md` **after** the hash, exactly as Hermes does it: an agent
learning something must not look like a configuration change.

### One persona, two harnesses

`hermes_render.PREAMBLE` and `hermes_render.handbook_block()` are not Hermes-specific — they are how
*this business* tells an agent who it is, what a `pending_approval` means, and that tool results are
information rather than orders. Copying them would let the two harnesses drift, and then an eval run
on one would not describe the other.

**Move both to `mcp/agent_runner/persona.py`** and have `hermes_render` and `claude_render` import
them. No wording changes in this slice: `hermes_render.render()` must produce the same
`profile_hash` for the same version after the move as before it, and the conformance suite asserts
that against a stored hash.

### Events, and what the run's outcome is read from

Each line of `stream-json` is parsed and handed to the runner's existing `_record()`, which already
writes both the live view and `agent_run_events`:

| stream-json | `agent_run_events` row |
|---|---|
| `assistant` message containing a `tool_use` block | `event=tool_call`, `tool_name`, `tool_call_id` |
| `user` message containing a `tool_result` block | `event=tool_result`, `tool_call_id`, `status` from `is_error`, duration measured between the two |
| `system` with `subtype=init` | `event=session_start`, `detail` = session id, model, the tools actually loaded |
| `result` | `event=session_end`, `status`, `detail` = turns, duration |

**The outcome is read from the final `result` event, never from the exit code** — the same lesson
H0 learned from Hermes (`RunOutcome` from `--usage-file`, because the exit code is 0 even when the
run failed). `result.is_error` or `subtype != "success"` ⇒ `RunOutcome("failed", …)`;
`result.result` is the answer; `result.usage` and `total_cost_usd` go into `usage_report`. The
proxy's ledger rows remain the system of record for cost — the CLI's number is recorded beside them,
and the conformance suite reports the difference rather than hiding it.

A run killed by `cancel()` returns `RunOutcome("cancelled", …)` on signal −9/−15/130, as Hermes does.

### The sandbox

`/usr/local/sbin/bos-agent-exec` currently hard-codes one binary:

```bash
[[ "$HERMES" == /opt/hermes/venv/bin/hermes ]] || { echo "bos-agent-exec: bad binary" >&2; exit 64; }
```

It becomes an **allow-list of two**, and the variable is renamed `AGENT_BIN`:

```bash
case "$AGENT_BIN" in
  /opt/hermes/venv/bin/hermes|/opt/claude-agent/bin/claude) ;;
  *) echo "bos-agent-exec: bad binary" >&2; exit 64 ;;
esac
```

The env-line filter gains `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `CLAUDE_CONFIG_DIR` and
`NODE_OPTIONS`; everything else about the launcher — `--uid=bos-agent`, `ProtectSystem=strict`,
`IPAddressDeny=any`, `ReadWritePaths` limited to the agent's own directory, credentials on stdin
rather than the command line — is untouched and must stay untouched.

**Install:** `/opt/claude-agent`, root-owned, read-only to `bos-agent`, pinned to an exact version
(`npm install --prefix /opt/claude-agent @anthropic-ai/claude-code@<version>`), with `bin/claude` as
the entry point. Node 24 is already on this host. Upgrading is the Hermes rule: bump the pin, run the
conformance suite, then evals. **[spike]** `MemoryMax` does **not** need raising: a scripted run peaked at 256 MB against the
existing 1500M ceiling. Re-measure after the first real run with a full context.

### Registry and the hire-time guard

`registry.py` gains one line: `for cls in (HermesHarness, ClaudeAgentHarness):`. That is the whole
change, and it is the proof the interface generalises.

The defect this slice also closes: **nothing refuses a hire onto a harness that does not exist.**
`model_registry.harness` admits five values; two will have harnesses. So:

- `mcp/agent_runner/registry.py` exposes `built_keys()`.
- `GET /health` on the runner reports it.
- The model form (`html/settings/models/form.php`) shows, per harness option, whether a harness is
  built, and `save.php` warns — but does not refuse — when an unbuilt one is chosen, because
  registering a model ahead of its harness is legitimate.
- The **hire** and **config-activate** handlers refuse: an agent may not be hired onto, or activated
  on, a model whose harness is not built, naming the harness and what is built. This is a refusal
  that names what is in the way, per the money slices' review lesson.

## Files (exactly these — no additions)

| File | Change |
|---|---|
| `mcp/agent_runner/persona.py` | **new** — `PREAMBLE`, `handbook_block()`, `HANDBOOK_CHARS` moved here verbatim |
| `mcp/agent_runner/hermes_render.py` | imports them; no behaviour change (hash asserted unchanged) |
| `mcp/agent_runner/claude_render.py` | **new** — renders `SYSTEM.md`, `mcp.json`, `settings.json`, the tool allow-list, the hash |
| `mcp/agent_runner/claude_harness.py` | **new** — `ClaudeAgentHarness(Harness)`: `version()`, `prepare()`, `execute()`, `cancel()` |
| `mcp/agent_runner/registry.py` | one tuple entry; `built_keys()` |
| `mcp/agent_runner/config.py` | `CLAUDE_BIN`, default `/opt/claude-agent/bin/claude` |
| `mcp/agent_runner/service.py` | parse `stream-json` lines into `_record()`; `/health` reports `built_keys()` |
| `mcp/claude_conformance/` | **new** — the suite below, its README the evidence for every claim in this spec |
| `/usr/local/sbin/bos-agent-exec` + `docs/deploy/bos-agent-exec` | two-binary allow-list, extra env keys, `MemoryMax` |
| `docs/deploy/claude-agent-install.md` | **new** — the pinned install, beside `hermes-install.md` |
| `html/agents/hire.php`, `html/agents/config-activate.php` | refuse an unbuilt harness, by name |
| `html/settings/models/form.php` + `web/components/settings/ModelForm.tsx` + `web/lib/schemas/settings.ts` | say which harnesses are built |
| `app/features/agents/runs.php` | `built_harnesses()` (asks the runner's `/health`) and `agent_harness_error()` |
| `mcp/hermes_conformance/dummy_llm.py` **[spike]** | decide the wire on the path alone — the CLI sends `/v1/messages?beta=true` |
| `mcp/agent_runner/ledger_proxy.py` **[spike]** | forward the incoming query string upstream |
| `mcp/agent_runner/store.py` **[spike]** | `last_payload()` PREFERS a call with tools instead of REQUIRING one |

No migration. No manifest entry (no new screen or action). No MCP tool.

### The platform changes the second harness forced **[spike]**

The spec said that if a second harness needs the platform to change, the interface was wrong and
that is the finding. Two small ones, both correctness fixes that have nothing to do with Claude:

1. **`ledger_proxy` dropped the incoming query string.** It rebuilt the upstream URL from scratch,
   so `?beta=true` never reached the provider. What was asked for should be what is sent.
2. **`store.last_payload()` required a call that carried tools**, to skip Hermes' auxiliary model
   calls. An agent with no tool grants makes only toolless calls, so a run that had just answered
   was told "no model call was recorded" (run 34). Tools are now a preference, not a filter.

Neither touched the `Harness` interface, `RunContext`, the run token, the MCP servers, memory,
skills or approvals. Adding the harness was one class, one renderer and one tuple entry.

## The conformance suite (`mcp/claude_conformance/`) — runs BEFORE the harness is wired in

H0's rule: prove every claim on this host, at the pinned version, and write the evidence down.
The suite is a script plus a README recording what it found, and it must be green before
`registry.py` is touched.

1. `--bare` with no `ANTHROPIC_API_KEY` and a stale keychain/OAuth present **fails to authenticate**
   rather than falling back to a logged-in account. *(The API-keys-only rule, proven.)*
2. `ANTHROPIC_BASE_URL` at a local stub is honoured for every call; with `IPAddressDeny=any`
   (localhost only) a run still completes, and a call aimed anywhere else fails rather than leaks.
3. `--strict-mcp-config` + `--mcp-config` attaches an HTTP MCP server with a bearer header, and
   `${BOS_RUN_TOKEN}` in the header is expanded from the process environment. **If it is not
   expanded, the renderer writes the literal token into `mcp.json` and the file is mode 0640 —
   record which of the two is true, and say so in the README.**
4. `--tools` with MCP tool names admits exactly those and denies a sibling tool on the same server.
5. `--restricted` genuinely removes Bash: a prompt that asks for a shell command is refused.
6. `stream-json` line shapes are what the event mapping above assumes — captured verbatim into the
   README, because this is a wire format we do not own.
7. The exit code lies at least once (a failed run exiting 0), or the README records that it does not
   and the outcome is still read from `result`.
8. Peak RSS of a real run, to set `MemoryMax`.
9. A cancelled run terminates within 5s and leaves no orphan Node process.
10. Two runs of the same config version produce the same `profile_hash`; changing a tool grant
    changes it.

## Acceptance (the demo this slice owes)

1. `mcp/claude_conformance/run_conformance.py` green, its README committed with the version pin.
2. `hermes_render` still renders Jack's active version to the **same `profile_hash`** as before the
   persona move — the existing Hermes agents are untouched by this slice.
3. Johnathan (38) runs. A manual run through `html/agents/run.php`: the answer comes back, the
   `agent_runs` row carries `harness='claude_agent_sdk'` and a real `sdk_version`, `prompt_ledger`
   has its calls with a cost, and `agent_run_events` has the tool calls with durations — **from
   stream-json, with no observer plugin.**
4. The same agent reads real business data through an MCP tool it was granted, and is refused a tool
   it was not.
5. An above-threshold action by a `claude_agent_sdk` agent pauses as an approval request and writes
   nothing — the approvals path is harness-independent, and this is the first proof of it through a
   second harness. *(It is also half of phase 5's exit criterion.)*
6. Hiring onto `openai_agents_sdk` is refused by name.
7. `systemctl restart maludb-os-agent-runner` and Jack's morning duty still runs on Hermes.

## What the acceptance produced (2026-09-20)

| # | Acceptance | Result |
|---|---|---|
| 1 | conformance green, README committed with the pin | 12 passed, 0 failed, 3 informational, Claude Code 2.1.278 |
| 2 | `hermes_render` unchanged | Becky's active version renders the **same hash under the old and the new code**. (Her hash differs from her last run because another session edited her grants or handbook between them — which is what the hash is for.) |
| 3 | Johnathan (38) runs | **run 33** — answered, `harness='claude_agent_sdk'`, `sdk_version='claude-agent-sdk 2.1.278 (Claude Code) (pinned 2.1.278)'`, one ledger row at 0.020408, three `agent_run_events` rows from stream-json with **no observer plugin** |
| 4 | a granted tool works, an ungranted one is refused | **run 35** — `find_contacts` called (250 ms, recorded), and asked for `pipeline` the agent reported it was not granted and *"did not look for another route"*, quoting its own persona rule. **A tool grant is not a data grant:** `find_contacts` returned empty because member 38 holds no `contacts` module grant, so `mcp_organizations` shows it nothing. Both rules held at once. |
| 5 | an above-threshold action pauses | owed — needs a write grant on a test agent; it is also half of phase 5's exit criterion and is proven in that step |
| 6 | hiring onto `openai_agents_sdk` is refused by name | *"No harness is built for openai_agents_sdk, so GPT-5 Agent could never run. Built: claude_agent_sdk, hermes. Choose a model on one of those."* |
| 7 | Hermes still runs after the restart | **run 36** — Becky answered on `hermes`, unchanged |

## Open Questions (must be EMPTY before a worker starts; workers append when escalating)

*(none)*
