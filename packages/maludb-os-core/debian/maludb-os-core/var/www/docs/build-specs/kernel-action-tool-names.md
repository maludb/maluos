# K55 — one name per action on the kernel's Actions MCP (2026-10-11)

**Found** while packaging MaluMail (Phase 0, 2026-10-11) and fixed at the owner's word ("Fix it").

## The defect

Every application's built actions become tools on the kernel's one Actions MCP (`mcp/application_actions.py`, A7), in one flat
list of names beside the kernel's own actions. `register()` read `mcp/registries/*.json` in file-name order and, when a name was
already taken, logged a warning and skipped the action. On this installation:

- **214 of 1,149 built application actions were not served** (935 were): 144 names are used by more than one application
  (`token_mint`, `settings_save`, `prefs_save`, `customer_create`, …), and two by an application and the kernel
  (`mcp_token_create`, `mcp_token_revoke`).
- **An agent granted a shared name was handed another application's tool.** Grants are stored by name on the one Actions MCP
  endpoint (`agent_tool_grants`), so Inventory's expert, granted `customer_create`, called the cidery's (cidery.json sorts
  first); ProcessCore's expert, granted `mcp_token_create` from its manifest, was served the kernel's.
- The service's log carried the warning 1,351 times across restarts; nobody reads it.

## The rule

Each built action carries a **`tool_name`** in its registry file (`app/features/applications/action_tool_names.php`):

1. its own action name, when no other application has a built action of that name and the kernel has no action of that name;
2. otherwise **`<app_key>_<action>`** (`inventory_customer_create`, `processcore_mcp_token_create`);
3. **a tool name once given is kept** while it is free. An application installed later that shares a name takes the prefix; the
   application that had the name keeps it — installing an application never renames another's tools or breaks its agents' grants.
   (A kernel action added later under an application's name takes the name back: that application's action is then prefixed and
   its grants must be moved — run `bin/actions_tool_names.php` again.)

A tool name is at most 64 characters of `[A-Za-z0-9_-]` (what model APIs accept); a name that cannot be given is reported and the
action is not served. The action's own name stays what the application, the approval hook and the activity log know it by — only
the name an agent calls changes. A single underscore, not `__`: Claude Code addresses an MCP tool as `mcp__<server>__<tool>`.

## The pieces

| Piece | Change |
|---|---|
| `mcp/application_actions.py` | serves each action under `tool_name(action)`; a name already taken is an **ERROR** naming the fix, never a quiet skip |
| `app/features/applications/action_tool_names.php` | the rule: `assign_registry_tool_names()` (one registry, against the others), `assign_all_tool_names()` (every registry), `application_action_tool_map()` (for hires), `kernel_action_names()`, `load_action_registries()` |
| `bin/actions_tool_names.php plan\|apply` | once, now (and after a kernel action takes an application's name): names every registry and **moves the grants** — a live Actions MCP grant on a name no longer served moves to the tool of the one application the agent works for (the applications whose MCP endpoints it holds grants on) that has the action; a grant on a kernel action's name held by an agent of an application with an action of that name moves too (it was meant for the application's). Several or none → listed for a person, left alone. Copies of the registry files in `mcp/registries/backup-<time>/`; the grants move in one transaction, each logged (`agent_tool_grant.revoke` + `.create`, `by` K55) |
| `bin/app_install.php` step 11 | names the application's actions as it writes its registry (kept names kept), and notes which are prefixed |
| `bin/hire_application_agent.php` | grants a declared Actions MCP action under the name the application's registry serves it as |
| `bin/test_action_tool_names.php` | the proof: the rule on synthetic registries, on copies of this installation's, and the Actions MCP's own `register()` over those copies — 16 checks |

## Applying it (the owner's)

```
php bin/actions_tool_names.php plan       # read-only: 1,149 of 1,149 served after, 356 prefixed, 148 grants to move, 0 left
php bin/actions_tool_names.php apply
sudo systemctl restart maludb-os-actions-mcp
php bin/test_action_tool_names.php
```

Between `apply` and the restart, the moved grants name tools the running server does not serve yet: restart at once. The way
back: copy the files in `mcp/registries/backup-<time>/` over the registries, restart, and re-grant the old names (the activity log
lists every move).

## For application authors (the plugin's `registration.md`)

Name actions so they are unlikely to be someone else's — the application's own nouns (`mail_send`, not `message_send`). A shared
name still works: the installer serves it as `<app_key>_<action>` and the hire script grants that name; job descriptions may keep
the bare name (an agent sees only the tools it holds, with their descriptions).
