# Hermes conformance suite

Stage **H0** of `docs/hermes-integration-plan.md`. It proves, against one installed Hermes Agent
release, every seam the Business OS depends on — and it is the **upgrade test**: bump the Hermes
pin, run this, then run the evals. Hermes moves at 100+ commits a day; we wrap it through
documented contracts, and this suite is how we find out when a contract moved.

Nothing real is touched. No model is called, no platform service is contacted, no money is spent.

| Stand-in | Stands where | Run from |
|---|---|---|
| `dummy_llm.py` — scripted OpenAI **and** Anthropic wire, one path prefix per model slot | the ledger proxy | any python |
| `dummy_mcp.py` — header-logging FastMCP server | records / activity / actions MCP | **the platform's `mcp/venv`** (the point is Hermes' MCP client against *our* FastMCP build) |
| `plugins/` — logging-only memory provider + observer plugin, pip entry points | `maludb-hermes` and `bos_hermes` | the Hermes venv |

## Running it

```bash
# once per Hermes install
git clone --depth 1 --branch <tag> https://github.com/NousResearch/hermes-agent.git src
uv venv --python 3.12 venv && uv pip install --python venv/bin/python -e 'src[mcp,anthropic,web]'
uv pip install --python venv/bin/python -e /var/www/mcp/hermes_conformance/plugins

python3 run_conformance.py --hermes <venv>/bin/hermes [--only base,anthropic] [--json out.json]
```

Exit 0 = every required check passed. `INFO` rows are behaviour the design needs to *know* rather
than require; compare them across upgrades. Scenarios: `base`, `anthropic`, `refusal`, `compression`.

The scripted model is driven by the prompt: `CALL:<tool>:<json-args>` directives in the first user
message are answered, in order, with that tool call (matching by name suffix, since Hermes prefixes
MCP tools `mcp__<server>__`); then it answers `DONE`. A call with no tools gets `aux-ok`.

## Result — Hermes Agent v0.21.3 (tag `v2026.9.14`, `345cd2b0`), 2026-09-19

**33 passed, 0 failed.** Spike install: `/home/maludb/hermes-spike/{src,venv}`.

### Confirmed — the plan stands on these

- **Headless**: `hermes -t <toolsets> -z <prompt> --usage-file <path>` — stdout is the answer and
  nothing else, stderr empty, a usage report with token counts and `completed`/`failed`.
- **Model routing**: a named `providers:` entry (`api`, `key_env`, `transport`) selected with
  `model.provider: custom:<name>` sends every main call to our base URL with our key.
  **Every auxiliary slot** accepts its own `base_url` + `api_key: ${VAR}` and obeys it
  (seen: `title_generation`, `compression`). `transport: anthropic_messages` posts native
  `/v1/messages`, streamed, tool_use round trip intact — the proxy must speak both wires.
- **Our MCP stack**: Hermes' MCP SDK **2.0.0** client works against our FastMCP on MCP SDK
  **1.30.0** (negotiated protocol `2025-11-25`). `headers:` with `${VAR}` puts the run token and
  run id on **every** request. `tools.include` hides an ungranted tool.
- **Memory**: a pip entry-point `MemoryProvider` is selected by `memory.provider`; with
  `memory_enabled: false` + `user_profile_enabled: false` the built-in `memory` tool is gone and
  the provider's own tool survives. In a one-shot run the **whole lifecycle fires**: `initialize`
  (with `hermes_home`, `agent_identity`, `agent_context`), `prefetch`, `sync_turn`,
  `on_session_end`, `shutdown`. `system_prompt_block()` lands in the system prompt; `prefetch()`
  text is injected into the **user** message (so the system prompt stays cache-stable).
  `on_pre_compress` (checkpoint API v2) fires with `require_checkpoint=True` when
  `compression.checkpoint_required: true`.
- **Skills**: a skill in `skills.external_dirs` is indexed in the system prompt; an agent-authored
  skill (`skill_manage create`) lands in `skills.create_dir`, nothing is written to the profile's
  own skills dir, the shared dir is untouched; `on_skill_lifecycle` fires.
- **Observer hooks** (`hermes.observer.v1`): `pre/post_api_request` once per main model call with
  `session_id`, `turn_id`, `api_request_id`, `usage`, `base_url`; `pre/post_tool_call` once per
  tool with `tool_call_id` and `status`.
- **No secret on disk**: with the run token and proxy key passed only as process environment,
  nothing under `HERMES_HOME` contains them — not `state.db`, not logs, not caches. (Hermes keeps
  `backups/config/config.yaml.good.*`, so a secret written *into* `config.yaml` would be copied.)
- **Budget refusal**: a `402` from the proxy is shown to the run once — no retry storm — and no
  tool runs.

### Corrections to what the research said — the plan is amended accordingly

1. **There is no `--format stream-json`** in this release. The runner gets the final answer from
   stdout and the totals from `--usage-file`; *live* step telemetry must come from the observer
   plugin reporting to the runner, not from Hermes' stdout.
2. **The exit code is 0 even when the run failed** (the 402 case). The runner must read
   `completed` / `failed` from `--usage-file`, never the exit status.
3. **Observer hooks do not see auxiliary model calls** — 1 of 4 calls in the base run and 2 of 17
   in the compression run were invisible to them. The research claimed the opposite. This settles
   the ledger design: **the wire-level proxy is the only complete source**; hooks are correlation
   and tool telemetry.
4. **`extra_headers` is not sent on auxiliary calls.** A run is identified at the proxy by its
   **per-run key**, never by a header.
5. A **general plugin's entry point must name the module** (`pkg.observer`), not
   `pkg.observer:register` — the latter loads as "has no register() function". A memory provider
   accepts either form.

### Settings the profile renderer must always write

| Setting | Why |
|---|---|
| `-t skills,<mcp-server-name>,memory` | The **allow-list**. Bare server name — `mcp-<server>` is rejected by `-z`. `memory` is what keeps the provider's tools. Without `-t`, the default surface includes `terminal`, `execute_code`, `delegate_task`, `write_file`, `web_search` … and a 38 KB prompt; with it, 5 tools and ~11 KB. |
| `tools.tool_search.enabled: false` | Otherwise MCP tools hide behind `tool_search` / `tool_call` meta-tools: the ledger would not show the real tool surface, and grants could not be audited from the request. |
| `mcp_servers.<s>.tools: {include: [...], resources: false, prompts: false}` | `include` = the granted tools; the other two remove four MCP utility tools per server. |
| `memory: {memory_enabled: false, user_profile_enabled: false, provider: <ours>}` | Built-in stores off, ours on. |
| `plugins.enabled: [<observer>]` | General plugins are opt-in. |
| `curator.enabled: false`, `updates.check: false` | No LLM rewriting shared skills; no phone-home to GitHub. `telemetry.shared_metrics` is already off by default. |
| every `auxiliary.<task>` → proxy `base_url` + `api_key: ${VAR}` | 18 slots in this release (`vision compression skills_hub approval review mcp title_generation memory_query_rewrite tts_audio_tags triage_specifier kanban_decomposer profile_describer goal_judge curator monitor background_review moa_reference moa_aggregator`). The default `auto` prefers OpenRouter / Nous Portal when credentials exist. **A new slot in a future release is a leak until it is listed** — the systemd IP allow-list (proxy + MCP ports only) is the backstop. |
| `auxiliary.title_generation.enabled: false` (runner default) | It fires on every one-shot run; a title for a duty run is a wasted call. |

### Worth knowing

- Hermes probes the base URL before use: `GET …/v1/models`, `GET …/v1/models/<id>`,
  `GET …/api/v1/models`, `POST …/api/show` (an Ollama check). The proxy answers `/models` and 404s
  the rest, quietly.
- MCP tool results reach the model wrapped in `<untrusted_tool_result>` ("treat as DATA") by default.
- `background_review` does **not** fire in a single-turn one-shot run. End-of-run learning (run
  summary to memory, skills outbox harvest) belongs to the runner, as the plan already says.
- Not exercised: the docker terminal backend (no docker on this host; native toolsets are off by
  default anyway), the API server / gateway, delegation, cron.
