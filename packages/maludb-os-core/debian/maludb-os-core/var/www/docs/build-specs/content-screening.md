# Build spec: screening what an agent is about to read (2026-09-20)

> Why: `docs/build-specs/eval-design-review.md`, safety gap 1 — Claude Architect Module 3 calls retrieved
> content and tool outputs "the dominant injection vector in enterprise deployments" and says to "screen
> retrieved content and tool outputs before they are appended to the model's context"; "instructions are
> not enforcement". Until today the only defence was a sentence in the persona. Agreed by the owner
> 2026-09-20, ahead of the eval runner.

## What it does

`mcp/content_screen.py` — deterministic, no model call. `scan(text)` returns hits; ordinary business text
returns none. It matches only text that **addresses the reader as a model** (overrides instructions, poses
as the system), **asks for concealment** from the people the agent answers to, **directs tool use**,
**asks for secrets or bulk data to be sent out**, or **hides characters** a person would not see.
Imperatives alone are not a hit — business text is full of them.

| Where | On a hit | Why that disposition |
|---|---|---|
| **Tool results** returned to an agent by the records, activity and memory MCP servers (`mcp/agent_grants.py`) | delivered with a PLATFORM NOTICE in front; recorded `flagged` | the agent still needs the data; the persona says what the notice means |
| **Recalled memory** injected by the runner (`agent_runner/memory.py`) | the item is left out; recorded `withheld`; a warning on the run | a planted note is the realistic way to steer an agent every morning, and nothing is lost by not recalling it |
| **Core memory** in the persona | the entry is left out; recorded `withheld`; a warning on the run | a person approved it, so a hit is something a person must look at |
| A **person's** tool call | not screened | people read records as they are |

Every hit lands in `agent_content_flags` (db/123): agent, run, source, the tool or namespace, which rule,
a 300-character excerpt, the disposition. The MCP servers are read-only roles, so they record through one
`SECURITY DEFINER` function, `record_content_flag()`, and can write nothing else. `mcp_agent_content_flags`
shows them to whoever may see the agent. A failure to record never breaks a tool call or a run.

## Proven

- 7 unit tests (`mcp/tests_content_screen.py`): five hostile samples caught and named; **thirteen ordinary
  sentences not flagged** — two of which the first draft got wrong ("Please send the statement to
  accounts@…", "System: QuickBooks Online") and the rules were narrowed for.
- **All 86 distinct tool results agents had been shown so far: 0 flagged.**
- A vendor created with an injection in its notes: Sasha's `get_organization` came back with the notice and
  the data, two flags recorded; the owner's call returned the record untouched.
- A hostile note planted in organisation memory: run 32 (Seamus) never saw it — "I have nothing on a SMOKE
  injection probe" — three flags recorded `withheld` against the run, a warning in the run's events.
  Both probes were removed afterwards (the memory through MaluDB's forget, which now removes the chunk).

## Not done

- The **actions** server's results are not screened (they are the platform's own words plus an echo of what
  the agent sent). The **assistant** is not screened: it acts as a person. Both are open.
- No classifier. The record of hits and misses is what would justify one.
- No screen shows the flags yet; they are reachable through the view. They belong on the agent's page and
  in the "signals" slice that comes next.
- Personas changed (one paragraph about the notice), so every agent's `profile_hash` changed today.
