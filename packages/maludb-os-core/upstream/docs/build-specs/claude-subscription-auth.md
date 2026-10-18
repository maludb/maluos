# Claude subscription login for agents (Max plan) — owner's own install only

Status: **APPROVED (owner, 2026-09-29: option 3, and §6 answers 2–4 "agreed") — building; token to be regenerated before it goes into runner.env.**
Reverses, for the owner's own installation only, the 2026-09-20 decision "API keys only — no claude.ai/Pro/Max login in the product"
(CLAUDE.md; `agent-runtime-claude-sdk.md`). Read with `agent-runtime-hermes.md`, `agent-runtime-claude-sdk.md`, `docs/model-providers.md`.

## Revisions after the spike and the build (2026-09-29) — these override anything below that disagrees

1. **Claude Code harness only. Hermes is NOT supported, by decision.** Given a subscription token, Hermes presents itself as Claude Code:
   `agent/anthropic_adapter.py` sends `user-agent: claude-code/<ver> (external, cli)`, `x-app: cli`, the OAuth-only betas, and prepends
   "You are Claude Code, Anthropic's official CLI for Claude." to the system prompt. That is impersonating Anthropic's client to use a
   subscription, and the platform will not route its agent fleet through it. The official CLI needs none of that: it *is* the client
   (the spike's mock showed it building its own `claude-cli/…` request). db/165 limits `auth_mode = 'claude_subscription'` to the
   `claude_agent_sdk` harness and removes the Hermes twin rows; the runner and the proxy refuse it on any other harness. Hermes agents stay on API keys.
2. **The token never reaches an agent (better than §2.3 above).** The CLI is launched with `CLAUDE_CODE_OAUTH_TOKEN` set to the **run's proxy key**, so it builds
   a normal login-style request with `Authorization: Bearer <run key>`; the ledger proxy identifies the run by that key as it always does and **replaces the bearer
   with the real token** — the same swap it makes for an API key. Nothing else in the request is touched. There is no pass-through route and no run key in a URL.
3. **The ledger:** a subscription call stores `cost = 0`, `notional_cost = list price`, `billing = 'subscription'` (db/164) — so every dollar total and statement
   that sums `cost` is right without a change, and `month_to_date_cost()` (budgets) sums both.
4. **Fences (proved, `mcp/claude_conformance` S0–S5, 20/20):** no `--bare`; instead `--restricted` (ignores user, project and local settings files), `--setting-sources ""`,
   `--strict-mcp-config`, `--no-session-persistence`, `CLAUDE_CODE_DISABLE_{AUTO_MEMORY,CLAUDE_MDS,ORG_MEMORY,POLICY_SKILLS,BUNDLED_SKILLS,NONESSENTIAL_TRAFFIC}`, and the
   empty per-agent HOME/config/cwd. The control (a plain default CLI) picks up three planted `CLAUDE.md` files and fires three planted hooks; the fenced launch loads none of it.
5. **Where it lives:** `mcp/agent_runner/claude_launch.py` (shared by the harness and the suite), `store.py` (refusals, one-at-a-time cap, notional ledger, budget),
   `ledger_proxy.py` (the swap), `service.py` (`/health.subscription`), `app/features/agents/runs.php` (`agent_harness_error()` refuses hiring/activating onto a
   Max-plan model while the switch is off), `docs/deploy/set-claude-subscription.sh on|off|status`, db/164–166.

## Build status

Steps 2–4 (Claude Code) built and committed; the runner has NOT been restarted with the new code and the feature is OFF. Remaining: the owner regenerates the token
and runs `set-claude-subscription.sh on <file>` (step 5), then one real turn on a `… · Max plan` model proves it end to end (ledger row `billing='subscription'`).

## 1. What and why

The owner's Hermes agent on a Mac Mini authenticates to Claude with a Max plan. Agents here that use Claude — on the **Hermes** harness
and on the **Claude Code (claude_agent_sdk)** harness — should be able to do the same, so their Claude calls draw on the plan
instead of API billing.

### The risk, accepted by the owner and stated here so it travels with the feature

Anthropic's terms have not allowed a *product* to offer claude.ai login or subscription limits to agents built on the Agent SDK, and a
subscription is sold for a person's ordinary use, not a fleet of autonomous agents running around the clock. Using it this way may breach
the terms, may be throttled or blocked at any time, and could put the **whole Max account** (the owner's own Claude access) at risk. This
is therefore:

- **off by default**, switched on by an explicit line in the runner's environment file, never by a screen;
- **for the owner's own single-tenant install** — never enabled for another tenant, never shipped on by default, never used to resell;
- clearly labelled wherever it can be chosen; and
- reversible in one step (remove the token and the switch; every agent falls back to its API-key model or is refused with a plain message).

Nothing here changes how an API-key model works.

## 2. Findings that shape the design

1. **`claude` in `--bare` mode cannot use a subscription.** The Claude harness launches the CLI with `--bare` precisely so an API key is the
   only way it can authenticate (`mcp/agent_runner/claude_harness.py`). A subscription needs the CLI *without* `--bare`, with
   `CLAUDE_CODE_OAUTH_TOKEN` (the long-lived token `claude setup-token` prints — intended for automation, valid about a year, no refresh
   flow to build). Without `--bare` the CLI would also load ambient settings, hooks, plugins and memory, so the run must be re-fenced with
   explicit flags and a clean per-agent config dir (the run already has its own `CLAUDE_CONFIG_DIR` and `HOME`); this is the part that needs a
   careful spike and the conformance suite (`mcp/claude_conformance/`) before it is trusted.
2. **Hermes already supports it.** `agent/anthropic_credentials.py` resolves `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_TOKEN`, handles the
   OAuth header shape itself, and reads `~/.claude/.credentials.json` as a fallback. We hand it the token; we write no header logic. (Hermes
   choosing the client identity it sends is Hermes's design, not ours; we neither add nor alter it.)
3. **The agent process would hold the token for the run.** Today agents never hold a provider key: the ledger proxy injects it. A
   subscription token is delivered to the process like the per-run proxy key is today (over stdin to the root-owned launcher, never on a
   command line, never on disk). The launcher runs the agent as its own unix user with **no network beyond localhost**, so the only place
   the token can go is the local proxy. The token is a long-lived credential for the whole account — that is the real cost of this design and
   is why the switch is off by default.
4. **The ledger must still see every call.** The proxy stays in the path in a **pass-through mode**: it forwards the client's own
   authentication headers unchanged (it does not inject, rewrite or fabricate credentials or client identity), records usage from the
   response, and prices it as **notional** (what the API would have cost) with `billing = 'subscription'` so spend statements never
   mistake it for money paid. Because the client's Authorization header now carries the subscription token, the run is identified by a run
   key **in the base-URL path** (`/anthropic-sub/<run key>/v1/messages`) instead of the auth header.

## 3. Design

| Piece | Change |
|---|---|
| Switch and credential | `/etc/business-os/runner.env`: `ALLOW_CLAUDE_SUBSCRIPTION=1` and `CLAUDE_CODE_OAUTH_TOKEN=…` (root-only, like provider keys, `docs/deploy/set-provider-key.sh` pattern). New `docs/deploy/set-claude-subscription.sh <token-file>`: reads from a file, checks it with one tiny `claude -p` call **before** restarting anything, backs up the env file, never prints the token. Removing either line disables the feature. |
| Model registry | db/164 (additive): `model_registry.auth_mode text NOT NULL DEFAULT 'api_key' CHECK (auth_mode IN ('api_key','claude_subscription'))`, and `prompt_ledger.billing text NOT NULL DEFAULT 'api'` (`'api'` \| `'subscription'`). Subscription models are separate rows ("Claude … · Max plan"), never a flag on an existing row, so an agent's model says plainly what it bills to. |
| Runner | `/health` reports `subscription: true|false`. Hiring or activating an agent onto a subscription model is **refused by name** when the switch is off (as an unbuilt harness already is, `agent_harness_error()`). |
| Claude harness | For `auth_mode = claude_subscription`: no `--bare`; env carries `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_BASE_URL` = the proxy's subscription path, no `ANTHROPIC_API_KEY`; the fences `--bare` gave (no hooks, no ambient settings, no plugins but ours, no memory) are re-established by flags and a scrubbed config dir, and **proven** by the conformance suite. |
| Hermes harness | `hermes_render.py` points Hermes' Anthropic provider at the same subscription path and passes the token as `CLAUDE_CODE_OAUTH_TOKEN`; no proxy key in `x-api-key`. |
| Ledger proxy | New route `POST /anthropic-sub/<run key>/v1/messages`: resolves the run from the path key, refuses unless the switch is on and the run's model is a subscription model, forwards **as received** to `https://api.anthropic.com`, streams back, ledgers with `billing='subscription'`, cost notional. Never logs an Authorization header. |
| Accounting | Statements and budgets: subscription rows are excluded from dollar totals and shown as their own line ("Max plan — notional $x"); a per-agent monthly budget counts notional cost only if the owner says so (open question 3). |
| Screens | Model form shows the auth mode and, for a subscription model, the warning above; AI Ops → Spend shows the split. Nothing to configure the token on a screen. |
| Activity | Setting the token is a script the owner runs, logged in the shell history and the journal, not in the app. Using a subscription model logs as any run does; the run row and ledger say `subscription`. |

## 4. What it does not do

Spoof, alter or fabricate client identity, headers or system prompts. Share the login with other tenants. Turn itself on. Route a Claude
call around the ledger. Store the token in the database or the repository. Use the plan for anything the API-key path still handles
(evals' judge, system_one, non-Claude providers).

## 5. Plan

| Step | Work | Proof |
|---|---|---|
| 0 | Owner generates a token (below) and decides §6. | token file present; answers recorded |
| 1 | **Spike, no code in the product:** with the token, run `claude` non-bare in a scratch config dir on this box through a throwaway pass-through, and Hermes once, to see what each actually sends and what the fences leak. Write it up here. | findings under "Spike" |
| 2 | db/164; registry rows; `/health` field; refusals; model form shows auth mode. | tests; nothing changes for API-key agents |
| 3 | Proxy pass-through route + `billing` ledgering; unit tests with a fake upstream; statements split. | proxy tests; a rolled-back statement check |
| 4 | Claude harness subscription launch; conformance suite extended (no hooks/plugins/memory/network leaks); Hermes harness render. | conformance green; one real turn each, ledgered as subscription |
| 5 | `set-claude-subscription.sh`; docs (`docs/deploy/claude-agent-install.md`, `hermes-install.md`); CLAUDE.md decision updated with this exception and its limits. | owner runs it; a real chat turn on a subscription model |

## 6. Decisions for the owner

1. **Token.** The token comes from `claude setup-token`, which opens a browser login as the Max account. Run it where you have a browser (the Mac
   Mini) and put the token in a file on this server (`chmod 600`, outside the repo), or run `! claude setup-token` here if this box can show you the
   link. I never see or store it outside `runner.env`.
2. **Which models.** Recommend adding subscription rows only for the models you actually run on the plan, and moving agents over one at a time,
   starting with a low-stakes one (Comms).
3. **Budgets.** Should a per-agent monthly budget count the notional cost of subscription calls (keeps a runaway agent stoppable) or ignore them?
   Recommend counting them.
4. **Shared limits.** All agents on one login share one Max rate limit; a busy agent can starve the rest. Recommend a cap of one concurrent
   subscription run unless you want more (a runner setting).

## Spike

**2026-09-29, step 1 (done).** The owner's `setup-token` token (`sk-ant-oat01-…`, in `~/.claude_runner.env`, mode 600, outside the repo) was used once, with the
official `claude` 2.1.278, **without `--bare`**, in a scratch `HOME`/`CLAUDE_CONFIG_DIR` and an emptied environment (`env -i`):

- **It authenticates.** `CLAUDE_CODE_OAUTH_TOKEN` alone is enough; the CLI answered a one-word prompt (`is_error:false`, model `claude-sonnet-5`).
  No proxy was in the path for this call, so the pass-through route (§3) is still untested against Anthropic — step 3's first proof.
- **The CLI prices its own call notionally**: `total_cost_usd` 0.0219 with `costBasis: "list"` — what the API would have charged. That is the number the ledger's
  `billing = 'subscription'` rows should carry, and the CLI's `usage` block gives the token counts the proxy will also see.
- **What non-bare mode brings in** (all in the config dir, none from the host): `policy-limits.json` (account restrictions/compliance flags — benign here),
  `remote-settings.json` (**empty** — the account has no remotely managed settings; if it ever does, that is an outside party's settings entering a run, so the harness
  must fail closed when it is non-empty), `.claude.json` (identity and migration flags), `projects/`, `sessions/`. No hook, plugin or `CLAUDE.md` was read because none existed in the scratch dirs.
- **The fences `--bare` gave, and their replacements** (`claude --help`): hooks/plugins/memory/CLAUDE.md discovery → an empty per-agent `HOME`, `CLAUDE_CONFIG_DIR` and `cwd`
  (already how the run is laid out), `--setting-sources` restricted to sources that hold only our rendered `settings.json`, `--settings`, `--strict-mcp-config`,
  `--disable-slash-commands` off/on as the persona needs, `--no-session-persistence`, `--restricted`, and the existing `--tools/--allowedTools` lists. Which of them actually
  suffice is what the extended conformance suite must prove in step 4 — a planted hook, plugin, CLAUDE.md and settings file in the agent's home and cwd must NOT run.
- **Not yet tested:** Hermes with this token; a run through the proxy; concurrency limits on the plan.

**Token hygiene note.** While inspecting the file the token was printed once into this session's output (the file holds the bare token, not `KEY=value`, so a masking
`sed` did not mask it). Regenerate it (`claude setup-token`) before it goes into `runner.env`; the script in step 5 stores it there and never prints it.
