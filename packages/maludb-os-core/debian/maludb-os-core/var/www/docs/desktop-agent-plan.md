# Plan — a voice-driven desktop agent that operates the platform's interface (Hermes Agent + Hermes voice)

Plan only; no code. 2026-09-20. This is the requirements' **desk** ("an enrolled desktop… a human works
there, resident agents run there while it is online, and it reaches local files the server never sees")
and the Hermes plan's deferred **desk runtime**, now with two additions from the owner: **voice**, and
**control of the platform's user interface**.

## What I checked first

**Hermes, in the release pinned on this server (v0.21.3, `/opt/hermes/src`) — read in source, not from docs:**

| Piece | What it is | Where |
|---|---|---|
| **Hermes Desktop** | an Electron app: chat with the full agent, side-by-side preview pane, file browser, **voice**; runs against a local Hermes install **or a saved remote connection to a gateway** | `apps/desktop/` |
| **Voice** | STT → turn → TTS, sentence-by-sentence streaming speech, push-to-talk (Ctrl+B) or continuous with silence detection, wake word, **barge-in** and a stop phrase; STT: local faster-whisper / Groq / OpenAI / Mistral / xAI; TTS: Edge / ElevenLabs / OpenAI / NeuTTS / Piper (local) …; a full-duplex "GPT-Live" mode at $0.05 a minute; with a remote gateway the desktop does STT/TTS itself and sends only text ("client-direct") | `hermes_cli/voice.py`, `gateway/run_voice.py`, `tools/tts_*`; the voice-mode doc page |
| **Browser control** | a broker that binds an identity-scoped *controller* (a browser extension) to the agent: `browser_navigate / click / type / press / scroll / snapshot / screenshot / tabs` — raw CDP and eval are developer-mode only | `gateway/browser_control_broker.py`, `tools/browser_extension_router.py` |
| **Computer use** | pixel-level control of the whole desktop through `cua-driver` (macOS, Windows, Linux), "does not steal the user's cursor" | `tools/computer_use/` |
| **Desktop-only tools** | tools that emit events to the desktop window that owns the turn | `tools/desktop_ui.py` |
| **Tool search** | built in — the setting we turned OFF for server agents because it hid their few MCP tools behind meta-tools | `tools.tool_search.enabled` |

The voice doc page describes the current release; whether every feature on it (GPT-Live, client-direct, wake
word) is in the pinned tag is a spike question, not an assumption.

**The platform already has the beginnings of a UI-control channel:** the command-bar assistant calls
`find_screen` and `navigate` over 237 registered screens, the React shell obeys the `navigate` and `refresh`
it gets back (`router.push`), the shell tells the assistant which screen, entity and record the person is on,
and — by design rule — **every meaningful element has a unique, stable id** and there are no modals. That last
rule was written as "the change-request vocabulary"; it is also exactly what makes an interface operable by
name instead of by pixel.

## The central design choice: how the agent "controls the interface"

| | A. Semantic control (the platform's own channel) | B. Browser control (Hermes broker + extension) | C. Computer use (pixels) |
|---|---|---|---|
| How | the agent calls `ui_*` tools; the platform pushes the intent to the person's open session; the React shell performs it by screen id and element id | the agent reads a DOM snapshot and clicks/types in the person's browser | the agent looks at screenshots and moves a virtual pointer |
| Speed / cost | one tool call, no vision, any model | several calls per step, large snapshots | slowest, vision model, most tokens |
| Reliability | deterministic — ids are a contract we own | breaks when markup shifts | breaks when anything shifts |
| Who acts | the platform knows it is the desk agent, and says so in the log | **the person's logged-in session** — every click is indistinguishable from the person's | same |
| Reach | our interface only | any website (bank, accountant's portal) | any application |

**Recommendation: A for the platform's own interface**, because it is ours: "if you could have written the
steps in code, you could have used a workflow" (Architect M1:556) applies to clicking our own buttons. B is
worth having later for *other people's* websites, behind explicit per-site permission. C is out of scope for
v1. B and C share a property that matters here: they act inside the person's session, so grants, approvals
and "who did this" all collapse into the person.

**What A consists of** (platform work, additive):
- a server→browser push channel per signed-in session (SSE), carrying UI intents addressed to that session only;
- a small tool family on the actions server: `ui_where` (what screen, record and visible fields the person is
  looking at), `ui_navigate` / `ui_open_record`, `ui_highlight` (point at an element by id), `ui_fill` (put
  values into a form's fields by id — **fill, never submit**), `ui_scroll_to`;
- the React shell performs them and reports back done / not found;
- **changing data stays where it is**: either the agent calls the action tool (the handler authorises, logs,
  applies approval policy), or it fills the form and the *person* presses Save. `ui_fill` + a spoken "save it"
  becomes the action tool call, not a synthetic click.

## Who the desk agent is

Two honest options. **(i) The person's assistant** — it acts as the person who is sitting there, exactly as
the command bar does today (a short-lived token minted for that person; the log says *person, via desk
assistant*). **(ii) A resident agent** — its own member, grants, budget, approvals, working at that desk.
**Recommendation: (i) first.** Voice control of *your own screen* is the command bar with a microphone, and the
person is there to see and stop it. (ii) is the requirements' "resident agents" and comes after, reusing the
server runner's model (run tokens, grants, approvals) — it should not drive a person's screen at all.

## Where Hermes runs, and how the rules survive the move to a desktop

Voice and local files need the desk; a conversation needs a long-lived session, which the server's one-shot
runs are not. So: **Hermes Desktop with a local runtime on the desk**, configured by the platform, never by hand.

| Rule today | How it holds on a desk |
|---|---|
| No agent holds a provider key | the desk's Hermes points at a **platform-hosted model endpoint** (the ledger proxy, published behind the public vhost with a desk-session key). Keys stay on the server |
| Every model call is in the prompt ledger | same endpoint — the proxy already writes the rows; they gain `surface = desk`, the desk and the person |
| Budgets refuse at the proxy | a per-person (or per-desk) monthly budget, enforced at the same place |
| Tools are what was granted, enforced server-side | the desk reaches the platform's MCP servers over HTTPS with the person's token — the allow-list in the public vhost already has `/mcp/*` |
| What an agent reads is screened | **must be extended**: today a *person's* tool calls are not screened, and the desk agent calls as a person. Screening has to key on "a model is reading this", carried by the token, not on member kind. (The command-bar assistant has the same gap — recorded as open today.) |
| 469 tools cost 255k tokens a call | Hermes' own **tool search** is the fix on the desk, and the reason to build it for the command bar too |
| Memory is MaluDB, never a local file | the Memory MCP server over HTTPS; Hermes' built-in memory off, as on the server |
| Evidence for later evaluation | ledger rows as above; tool events through the observer plugin, posting to the platform instead of localhost; a thumbs verdict on spoken answers |

## Voice

- **Default: private and free** — local faster-whisper for speech-to-text, Piper (or NeuTTS) for speech. Nothing
  spoken leaves the desk; only the transcript goes to the model, through the ledger. Cloud STT/TTS (Groq,
  ElevenLabs, OpenAI) is a per-desk opt-in and another row in `docs/model-providers.md`.
- **Push-to-talk first**, wake word later; barge-in on; a stop phrase; audio is never stored, the transcript is
  the user message.
- **Spoken confirmation for anything that changes data**, reusing the action manifest's `confirm` flag; deletes
  and sends always read back what will happen.
- **Latency is the product**: STT ~0.5–2 s + model + TTS ~1 s. The model choice is a spike measurement —
  candidates already registered: Sonnet 5, DeepSeek Flash, GPT-OSS 120B on Fireworks.
- GPT-Live (full duplex) is attractive and is a fourth provider seeing business speech; not in v1.

## Stages

| Stage | Deliverable |
|---|---|
| **D0 Spike** (throw-away, like H0) | Hermes Desktop on one real desk: voice with local STT/TTS; a custom provider pointed at a remote endpoint; MCP over HTTPS with a bearer; which observer hooks fire in desktop sessions; tool search with 469 tools; what the preview pane can host; version skew between the desktop release and the server's pin. Output: a conformance checklist |
| **D1 Spec + checkpoint** | build spec; schema (desk sessions, desk budgets, UI intents); the `ui_*` tools and manifest rows; requirements + build plan synced. **Owner approves schema + tools + manifest together** |
| **D2 Desk enrolment** | enrol a desk, mint its session, publish the model endpoint and its keys, per-person budget, ledger `surface` |
| **D3 UI-control channel** | the push channel, the `ui_*` tools, the React shell's executor; `ui_where` first, then navigate/highlight, then fill |
| **D4 Voice profile** | the platform renders the desk's Hermes profile (voice, provider, MCP, tool search, memory off, observer); confirmations by voice |
| **D5 Local resources** | a drop folder and file picker that upload through the Documents action — the requirements' original reason for a desk |
| **D6 Safety + evidence** | model-reader screening by token; verdicts on spoken answers; desk rows in the control register |
| Later | browser control for named external sites (B); resident agents at a desk (ii); wake word; GPT-Live |

## Decisions for the owner (recommendations stated)

1. **Control mechanism** — semantic `ui_*` channel for our interface (A); browser control later for external
   sites only; no pixel control in v1. *Recommended.*
2. **Identity** — the desk agent is the person's assistant, acting as the person and logged as such; resident
   agents at a desk are a later stage and never drive a person's screen. *Recommended.*
3. **Where it runs** — Hermes Desktop with a local runtime on the desk, all model calls through a
   platform-hosted ledger endpoint. *Recommended.* (Alternative: a Hermes gateway on the server with the
   desktop as a thin client — simpler to secure, but it cannot see local files.)
4. **Voice privacy** — local STT and TTS by default; cloud voices opt-in per desk. *Recommended.*
5. **`ui_fill` never submits** — a save is always the action tool or the person's own click. *Recommended.*
6. **Which machine is the first desk** (macOS / Windows / Linux) — decides the spike. *Owner's.*
7. **Ordering against the agreed queue** (Monday check → signals slice → eval runner → assistant tool search).
   Tool search is now needed by both the command bar and the desk, so it moves up. *Suggested: D0 spike in
   parallel whenever a desk machine is available; D1 after the signals slice.*

## Risks

- Hermes Desktop moves weekly; the server pins one release. Wrap, never fork — the same rule as the server,
  with a conformance suite per surface.
- A public model endpoint is a new attack surface: short-lived keys bound to an enrolled desk and a person,
  rate limits, budgets, and nothing but the two wire routes.
- Voice makes mistakes (Whisper hallucinates on silence; Hermes filters 26 known phrases). Every data change
  needs the read-back.
- A desktop holds a token that acts as a person. It must be revocable per desk, expire, and be useless
  off that desk's enrolment.

## State

- **2026-09-20 — the first desk is the owner's Mac.** Desk-side code lives in a separate private repo,
  `github.com/maludb-ed/business-os-desk` (the platform repo is not split and is not needed on the Mac). Pushed
  there: the README (what the repo is, the rules a desk keeps, the contract with the platform), `docs/HANDOFF.md`
  (the Mac half of the D0 spike — twelve questions only a real desk can answer — setup, config to try, the rules),
  a results form, a `CLAUDE.md` for a Claude Code session on the Mac, a `.gitignore`. The Mac half is read-only
  against the platform: only the records and activity MCP servers are published today; actions, memory, the model
  endpoint and `ui_*` are stage D2/D3 work here. The owner has not yet confirmed the plan's five recommendations.
  Headless half of the spike (this server): not started.
- **2026-09-20 — D0 headless half done** (results: desk repo `docs/spike/D0-headless-results.md`). What it
  changes here: (1) Hermes' installer tracks `main`, 4,168 commits past the release we pin — a desk is installed
  with `--commit` at the server's pin and its updates are the platform's to control; (2) the 469-tool surface costs
  161k tokens a call with tool search off, 3 tools with it on (5 of 6 questions still reached the right tool, in up
  to 11 model calls), and a curated dozen tools is fastest — so the desk agent, **and the command bar**, get a
  curated set with search as the fallback; (3) one-shot Hermes takes 8–10 s to start and a warm gateway turn still
  costs ~4 s before model time, so voice needs a long-lived session and a fast model; (4) Hermes' own
  `/v1/capabilities` says tools execute on the gateway's host — Hermes belongs on the desk, as recommended;
  (5) in gateway mode native tools are ON by default: the rendered desk profile must set `platform_toolsets`;
  (6) records and activity MCP answer over HTTPS with a personal token; publishing actions and memory for desks is
  a D2 security decision. Mac half: the owner's, not started.
