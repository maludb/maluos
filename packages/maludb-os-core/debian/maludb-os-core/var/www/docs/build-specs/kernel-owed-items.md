# Kernel owed items — what the integration contract found missing (A7)

2026-09-22 · Business OS build plan, phase 7 Part A, step A7. The seven items the plugin's
references recorded on 2026-09-21 as owed by the platform; (e) was withdrawn by the design of
2026-09-22 (an application makes no model calls of its own — A6 runs its expert in the kernel).
Built the same day.

| Item | What was built | Where |
| --- | --- | --- |
| (a) The renderers attach an application's endpoints | Both harness renderers attach an MCP endpoint with `${BOS_RUN_TOKEN}` when it is bearer and belongs to the platform or to an application whose catalog kind is `ours`; anyone else's stays skipped with the warning | `mcp/agent_runner/store.py` (`catalog_kind` on each granted endpoint; app_runner reads the catalog — db/139), `hermes_render.py`, `claude_render.py` |
| (b) The run-facts call | `POST /api/v1/runs/facts.php`, application token, body `{token}`: the signature alone is checked (an application never holds the relay key — `verify_token_signature()` in `app/auth.php`); answers `valid, is_agent, member_id, member_name, run_id, request_id, trigger, is_eval, run_status, endpoints[{id, name, url, mcp_surface_version, tools{name: constraints}}]` for this application's endpoints only | `html/api/v1/runs/facts.php` |
| (c) Application registries on the one Actions MCP | `mcp/registries/<app_key>.json` (format in its README) → one tool per built action, posting to the application's internal base URL with the caller's token and the relay; a name in an entity param resolved through the application's own `find_*` tool with the caller's token; the eval control unchanged (`app_post`) | `mcp/application_actions.py`, `mcp/actions_server.py` (`app_post(path, fields, base)`) |
| (d) The approval hook and replay | Before posting an action with an approval category the actions server asks `html/approvals/hook.php` as the caller; a matching policy records the request with the application's handler URL and body (202 `pending_approval`), an approval replays it to that absolute URL signed over the handler's path, so the application verifies exactly as a kernel handler does. **Fixed 2026-09-28:** the server asked the hook about the action's key (it read `log`; the registry writes `log_event`), so no policy ever matched an application's action — an agent's `issue_delete` reached Projects instead of pausing; now it pauses (request 28) | `html/approvals/hook.php`, `app/business.php` (`create_approval_request` takes the handler and body), `app/features/approvals/replay.php` |
| (f) `application_catalog.kind = 'ours'` | The third kind; `application_catalog_save` (super-admin) adds an `ours` or `external` entry: key, name, business area, kind, description, icon, category, vendor; the kernel's own entries are refused | db/139, `html/applications/catalog-save.php` |
| (g) Skills for the Claude harness | The synced skills reach a `claude_agent_sdk` agent two ways: inline in its persona (name, description, SKILL.md text, capped at 6,000 characters each, 12 skills) and as a plugin (`<agent_dir>/plugin`, `--plugin-dir`) so `/skills:<name>` resolves; skills are synced before the profile is rendered; the session-start event now records the CLI's skills and plugins | `claude_render.py` (`skills_section`, the plugin dir), `claude_harness.py`, `service.py` |

## Proven (test application, then retired)

- (f) the catalog entry added as `ours`; a kernel key refused (422).
- (a) with the test application registered against that entry and an MCP endpoint granted to Sasha, the runner loads the endpoint as `ours` and both renderers attach it (Hermes toolset, Claude `mcp__records__find_things`); the grant and endpoint were retired afterwards so her duties are unaffected.
- (b) a run token for Sasha's chat run answers `is_agent`, run 67, trigger `chat`, not an eval, the tool on the test endpoint; a person's token answers `is_agent:false`; a bad token `valid:false`; no application token 401.
- (c) a test registry whose action posts to the kernel's own department handler: the tool appears on the Actions MCP and creates the department.
- (d) with an `everyone` policy on that action's event, the same call answers `pending_approval` with a request whose handler is the absolute URL; approving it replays there and the department is created; the request is `executed`.
- (g) the Claude agent, asked without tools which skills it has, names its assigned skill and what it is for (run 74); the CLI's own session record lists the plugin and `skills:file-a-vendor-bill`.

## Open

- The pinned CLI (2.1.278) in `--bare --restricted` mode does not expose a `Skill` tool through `--tools`; the inline persona is what the agent works from, and a person's instruction may still name `/skills:<name>`.
- Entity resolution through an application's `find_*` tool is written to the registry format and exercised only in code review: no application from us exists yet to resolve against.
- `record_id` on a chat answer's actions (A6) would come from the actions server putting it into the tool event; not yet.
