# Application registries (A7, 2026-09-22)

One file per application from us, written by the installation agent when it installs the
application beside the kernel: `<app_key>.json`. The actions server (`mcp/actions_server.py`,
`mcp/application_actions.py`) loads every file here at start and puts each built action of the
application on the kernel's ONE Actions MCP — tool grants enforced here, an evaluation's write
recorded and never sent, the relay key never handed out, and the approval hook asked before an
action with an approval category is posted. Restart `maludb-os-actions-mcp` after adding one.

```json
{
  "schema": "maludb-os.registry/1",
  "app_key": "reservations",
  "name": "Reservations",
  "base_url": "http://127.0.0.1:8101",
  "records_url": "https://reservations.subello.com/mcp/records",
  "resolve": {
    "booking": {"tool": "find_bookings", "query_param": "q", "id_field": "booking_id",
                "label_field": "title", "params": ["booking", "booking_id"]}
  },
  "registry": { "...": "the application's own mcp/action_registry.json, as bin/build_action_registry.php writes it" }
}
```

`base_url` is the application's internal PHP port (never its public name); `records_url` is
where its records MCP answers, used to turn a name into an id with the caller's own token;
`resolve` names, per entity, the application's `find_*` tool and which action params carry that
entity. A file with a malformed shape is skipped and logged; an action whose name collides with a
tool already registered is skipped and logged.
