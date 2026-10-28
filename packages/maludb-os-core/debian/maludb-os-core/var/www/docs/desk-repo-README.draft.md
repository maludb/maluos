# Business OS Desk

The desk side of the Business OS: what gets installed on a person's computer so they can **talk to the
platform and have it operate its own interface for them**. It wraps [Hermes Agent](https://github.com/nousresearch/hermes-agent)
and Hermes voice; it does not fork them.

> **Status: nothing is built yet.** This repo starts with the D0 spike. The plan, the decisions behind it
> and the stage list live in the platform repo: `docs/desktop-agent-plan.md`.

## What this repo is — and is not

**Is:** the small amount of code that runs on a desk.
- enrol this computer with a Business OS tenant, and keep its desk token in the OS keychain
- fetch the Hermes profile the **platform renders** (model endpoint, MCP servers, tool search, voice,
  memory off, observer) — a desk is configured by the platform, never by hand
- the observer plugin that reports tool events back to the platform
- per-OS setup and checks (audio devices, push-to-talk, keychain)
- a conformance suite for the desktop surface, re-run on every Hermes upgrade

**Is not:** the platform. No database, no PHP, no React, no MCP servers, no provider keys. Those stay on the
server. This repo must never contain the platform's secrets, deployment details or history.

## The rules a desk keeps

1. **No provider key on a desk.** Every model call goes to the platform's model endpoint, which holds the
   keys, writes the prompt ledger and enforces the budget.
2. **The desk agent is the person's assistant.** It acts as the person sitting there and is logged that way.
3. **It operates the platform's interface by name, not by pixel** — `ui_*` tools that the platform pushes to
   the person's open session. It can fill a form; it never submits one. Saving is an action tool call or the
   person's own click.
4. **Voice is local by default** — speech-to-text and text-to-speech run on the desk; only the transcript
   leaves it. Cloud voices are an explicit opt-in.
5. **Anything that changes data is read back and confirmed aloud first.**
6. **A desk can be revoked** from the platform, and its token is useless anywhere else.

## The contract with the platform

Everything between a desk and the platform is HTTPS, and versioned. *(To be defined in D1 — listed here so
the boundary is clear from day one.)*

| Surface | Purpose |
|---|---|
| Enrolment API | register this desk, receive a desk token |
| Profile endpoint | the rendered Hermes profile for this desk and person |
| Model endpoint | OpenAI-wire and Anthropic-wire routes, desk-session key, ledgered |
| MCP servers (`/mcp/*`) | records, activity, actions (incl. `ui_*`), memory |
| Events endpoint | tool events from the observer plugin |

## Platforms

macOS first (it is where the first desk is), Windows second, Ubuntu desktop last. The code stays OS-neutral;
only setup, audio, the push-to-talk hotkey and token storage differ.

## Stages

D0 spike → D1 spec and owner's approval → D2 enrolment → D3 UI control → D4 voice profile → D5 local files →
D6 safety and evidence. See the plan for what each delivers.

## Development

*(Filled in by the D0 spike: Hermes Desktop version pinned, how to point it at a tenant, how to run the
conformance suite.)*

## License

*(Owner to decide.)*
